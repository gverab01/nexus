import { useState, useRef, useCallback } from 'react';
import { syncLeadWithLinkedIn } from '../services/api';

/**
 * Hook para la gestión de cola asíncrona serializada de sincronización con LinkedIn.
 * Permite encolar múltiples prospectos (individuales o en bloque) y ejecutarlos
 * secuencialmente de forma segura, evitando colisiones de navegación en Chromium
 * y respetando los intervalos antibaneo orgánicos.
 */
export function useSyncQueue({ onLeadUpdated = null, onQueueCompleted = null } = {}) {
  const [syncingLeadIds, setSyncingLeadIds] = useState(new Set());
  const [activeSyncingLeadId, setActiveSyncingLeadId] = useState(null);
  const [syncQueue, setSyncQueue] = useState([]);
  const [syncQueueStats, setSyncQueueStats] = useState({ total: 0, completed: 0, failed: 0 });

  // Referencias para control sincrónico sin stale closures
  const queueRef = useRef([]);
  const syncingIdsRef = useRef(new Set());
  const isProcessingRef = useRef(false);
  const cancelRequestedRef = useRef(false);
  const statsRef = useRef({ total: 0, completed: 0, failed: 0 });

  // Pausa antibaneo orgánica con jitter
  const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

  // Bucle procesador de la cola
  const processQueue = useCallback(async () => {
    if (isProcessingRef.current) return;
    isProcessingRef.current = true;
    cancelRequestedRef.current = false;

    while (queueRef.current.length > 0) {
      if (cancelRequestedRef.current) {
        // Cancelación solicitada por el usuario
        const remaining = [...queueRef.current];
        queueRef.current = [];
        remaining.forEach((item) => syncingIdsRef.current.delete(item.id));
        setSyncingLeadIds(new Set(syncingIdsRef.current));
        setSyncQueue([]);
        break;
      }

      const currentItem = queueRef.current.shift();
      setSyncQueue([...queueRef.current]);
      setActiveSyncingLeadId(currentItem.id);

      try {
        const res = await syncLeadWithLinkedIn(currentItem.id);
        if (res && res.lead) {
          if (onLeadUpdated) {
            onLeadUpdated(res.lead, res);
          }
        }
        statsRef.current.completed += 1;
      } catch (err) {
        console.error(`[SyncQueue] Error sincronizando lead ${currentItem.id}:`, err);
        statsRef.current.failed += 1;
      } finally {
        syncingIdsRef.current.delete(currentItem.id);
        setSyncingLeadIds(new Set(syncingIdsRef.current));
        setSyncQueueStats({ ...statsRef.current });
      }

      // Pausa antiban orgánica entre perfiles si quedan más elementos en la cola
      if (queueRef.current.length > 0 && !cancelRequestedRef.current) {
        await sleep(1600 + Math.random() * 800);
      }
    }

    setActiveSyncingLeadId(null);
    isProcessingRef.current = false;

    if (onQueueCompleted && statsRef.current.total > 0) {
      onQueueCompleted({ ...statsRef.current });
    }
  }, [onLeadUpdated, onQueueCompleted]);

  // Encolar una lista de prospectos
  const enqueueLeads = useCallback((leadsList) => {
    if (!Array.isArray(leadsList) || leadsList.length === 0) return;

    const itemsToAdd = [];
    for (const item of leadsList) {
      const id = typeof item === 'string' ? item : item?.id;
      if (!id) continue;
      // Evitar duplicados si ya está en proceso o en cola
      if (syncingIdsRef.current.has(id)) continue;

      syncingIdsRef.current.add(id);
      itemsToAdd.push({
        id,
        nombre: item?.nombre || item?.name || 'Prospecto'
      });
    }

    if (itemsToAdd.length === 0) return;

    // Actualizar cola y estados
    queueRef.current.push(...itemsToAdd);
    setSyncingLeadIds(new Set(syncingIdsRef.current));
    setSyncQueue([...queueRef.current]);

    // Si la cola estaba vacía y no había proceso, inicializar estadísticas
    if (!isProcessingRef.current) {
      statsRef.current = { total: itemsToAdd.length, completed: 0, failed: 0 };
    } else {
      statsRef.current.total += itemsToAdd.length;
    }
    setSyncQueueStats({ ...statsRef.current });

    // Iniciar procesamiento si no está ya en marcha
    processQueue();
  }, [processQueue]);

  // Encolar un único prospecto
  const enqueueLead = useCallback((lead) => {
    if (!lead) return;
    enqueueLeads([lead]);
  }, [enqueueLeads]);

  // Cancelar la cola pendiente
  const cancelQueue = useCallback(() => {
    cancelRequestedRef.current = true;
    const remaining = [...queueRef.current];
    queueRef.current = [];
    remaining.forEach((item) => syncingIdsRef.current.delete(item.id));
    setSyncingLeadIds(new Set(syncingIdsRef.current));
    setSyncQueue([]);
  }, []);

  return {
    syncingLeadIds,
    activeSyncingLeadId,
    syncQueue,
    syncQueueStats,
    isProcessing: Boolean(activeSyncingLeadId || syncQueue.length > 0),
    enqueueLead,
    enqueueLeads,
    cancelQueue
  };
}

