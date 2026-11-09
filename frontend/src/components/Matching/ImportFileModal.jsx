// Modal para importar prospectos en bloque al buzón de matching desde archivo CSV o TSV
import React, { useState, useRef } from 'react';
import { X, Upload, FileSpreadsheet, AlertCircle, CheckCircle2 } from 'lucide-react';
import { importBatchStagingLeads } from '../../services/api';

export default function ImportFileModal({ onClose, onImported, activeTenantWorkspace = '' }) {
  const [file, setFile] = useState(null);
  const [rawRows, setRawRows] = useState([]);
  const [headers, setHeaders] = useState([]);
  const [nameField, setNameField] = useState('');
  const [instField, setInstField] = useState('');
  const [emailField, setEmailField] = useState('');
  const [cargoField, setCargoField] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [errorMsg, setErrorMsg] = useState('');
  const fileInputRef = useRef(null);

  function handleFileChange(e) {
    const selectedFile = e.target.files[0];
    if (!selectedFile) return;
    setErrorMsg('');
    setFile(selectedFile);

    const reader = new FileReader();
    reader.onload = (event) => {
      try {
        const text = event.target.result;
        parseCSVText(text);
      } catch (err) {
        setErrorMsg(`Error procesando archivo: ${err.message}`);
      }
    };
    reader.readAsText(selectedFile, 'UTF-8');
  }

  function parseCSVText(text) {
    const lines = text.split(/\r\n|\n|\r/).filter(l => l.trim().length > 0);
    if (lines.length < 2) {
      setErrorMsg('El archivo debe tener al menos una fila de encabezados y un registro.');
      return;
    }

    // Detectar delimitador (coma, punto y coma o tabulación)
    const firstLine = lines[0];
    let delimiter = ',';
    if (firstLine.includes(';') && (firstLine.split(';').length > firstLine.split(',').length)) {
      delimiter = ';';
    } else if (firstLine.includes('\t') && (firstLine.split('\t').length > firstLine.split(',').length)) {
      delimiter = '\t';
    }

    const rawHeaders = firstLine.split(delimiter).map(h => h.trim().replace(/^["']|["']$/g, ''));
    setHeaders(rawHeaders);

    const parsedRows = [];
    for (let i = 1; i < lines.length; i++) {
      const line = lines[i];
      if (!line.trim()) continue;
      const cols = line.split(delimiter).map(c => c.trim().replace(/^["']|["']$/g, ''));
      const rowObj = {};
      rawHeaders.forEach((h, idx) => {
        rowObj[h] = cols[idx] || '';
      });
      parsedRows.push(rowObj);
    }

    setRawRows(parsedRows);

    // Auto-detectar columnas probables
    const lowerHeaders = rawHeaders.map(h => h.toLowerCase());
    const detect = (keywords) => {
      const idx = lowerHeaders.findIndex(h => keywords.some(k => h.includes(k)));
      return idx !== -1 ? rawHeaders[idx] : '';
    };

    setNameField(detect(['nombre', 'name', 'contacto', 'persona']));
    setInstField(detect(['colegio', 'institucion', 'empresa', 'escuela', 'establecimiento', 'account', 'company']));
    setEmailField(detect(['email', 'correo', 'mail']));
    setCargoField(detect(['cargo', 'puesto', 'rol', 'title', 'funcion']));
  }

  async function handleImport() {
    if (!nameField) {
      alert('Debes seleccionar al menos la columna del Nombre');
      return;
    }

    const formatted = rawRows.map(r => ({
      nombre: r[nameField] || '',
      institucion: r[instField] || '',
      email: r[emailField] || '',
      cargo_declarado: r[cargoField] || '',
      origen: 'CSV'
    })).filter(r => r.nombre.trim().length > 0);

    if (formatted.length === 0) {
      alert('No hay registros válidos con nombre para importar.');
      return;
    }

    try {
      setSubmitting(true);
      const res = await importBatchStagingLeads({
        leads: formatted,
        origen: 'CSV',
        tenant_id: activeTenantWorkspace || undefined
      });

      alert(`Importación completada:\n• ${res.creados || 0} prospectos ingresados al buzón\n• ${res.ignorados_o_duplicados || 0} ignorados o duplicados.`);
      if (onImported) onImported();
      onClose();
    } catch (err) {
      alert(`Error en importación: ${err.message}`);
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div 
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/75 backdrop-blur-xs p-4 font-sans"
      onClick={onClose}
    >
      <div 
        className="w-full max-w-xl bg-[#121316] border border-white/[0.08] rounded-xl shadow-2xl overflow-hidden relative z-10 flex flex-col max-h-[90vh]"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="p-4 border-b border-white/[0.06] flex items-center justify-between shrink-0">
          <div className="flex items-center gap-2.5">
            <div className="w-7 h-7 rounded-md bg-white/[0.04] border border-white/[0.08] flex items-center justify-center text-zinc-300">
              <FileSpreadsheet className="w-3.5 h-3.5" />
            </div>
            <div>
              <h3 className="text-xs font-semibold text-zinc-100">Importación Masiva (CSV / TSV)</h3>
              <p className="text-[11px] text-zinc-400">Ingresa bases de contactos para cruzarlas con LinkedIn</p>
            </div>
          </div>
          <button 
            type="button"
            onClick={onClose}
            className="p-1 rounded-md text-zinc-400 hover:text-white hover:bg-zinc-800 transition cursor-pointer"
          >
            <X className="w-3.5 h-3.5" />
          </button>
        </div>

        {/* Contenido scrolleable */}
        <div className="p-4 space-y-4 text-xs overflow-y-auto">
          {/* Zona de subida */}
          <div 
            onClick={() => fileInputRef.current?.click()}
            className="border-2 border-dashed border-white/[0.12] hover:border-zinc-500 rounded-xl p-5 text-center cursor-pointer transition bg-[#0D0E12] space-y-2"
          >
            <input 
              ref={fileInputRef}
              type="file" 
              accept=".csv,.tsv,.txt"
              onChange={handleFileChange}
              className="hidden" 
            />
            <div className="w-8 h-8 rounded-full bg-zinc-800 mx-auto flex items-center justify-center text-zinc-300">
              <Upload className="w-4 h-4" />
            </div>
            <div>
              <p className="text-xs font-medium text-zinc-200">
                {file ? file.name : 'Haz clic para seleccionar tu archivo CSV o TSV'}
              </p>
              <p className="text-[11px] text-zinc-500">
                {file ? `${rawRows.length} registros detectados` : 'Archivos exportados de Excel, Google Sheets o CRM'}
              </p>
            </div>
          </div>

          {errorMsg && (
            <div className="p-3 rounded-lg bg-red-950/40 border border-red-500/30 text-red-300 flex items-center gap-2 text-xs">
              <AlertCircle className="w-4 h-4 shrink-0" />
              <span>{errorMsg}</span>
            </div>
          )}

          {/* Mapeo de columnas si se cargó un archivo */}
          {headers.length > 0 && (
            <div className="space-y-3 pt-2">
              <h4 className="text-[11px] font-semibold text-zinc-300 uppercase tracking-wider">
                Mapeo de Columnas
              </h4>
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                <div>
                  <label className="block text-zinc-400 mb-1 font-medium text-[11px]">
                    Columna de Nombre <span className="text-emerald-400">*</span>
                  </label>
                  <select
                    value={nameField}
                    onChange={(e) => setNameField(e.target.value)}
                    className="w-full bg-[#0D0E12] border border-white/[0.08] px-2.5 py-1.5 rounded-md text-zinc-200 focus:outline-none focus:border-zinc-500 cursor-pointer"
                  >
                    <option value="">Seleccionar columna...</option>
                    {headers.map(h => <option key={h} value={h}>{h}</option>)}
                  </select>
                </div>

                <div>
                  <label className="block text-zinc-400 mb-1 font-medium text-[11px]">
                    Columna de Colegio / Institución
                  </label>
                  <select
                    value={instField}
                    onChange={(e) => setInstField(e.target.value)}
                    className="w-full bg-[#0D0E12] border border-white/[0.08] px-2.5 py-1.5 rounded-md text-zinc-200 focus:outline-none focus:border-zinc-500 cursor-pointer"
                  >
                    <option value="">(Ninguna)</option>
                    {headers.map(h => <option key={h} value={h}>{h}</option>)}
                  </select>
                </div>

                <div>
                  <label className="block text-zinc-400 mb-1 font-medium text-[11px]">
                    Columna de Correo Electrónico
                  </label>
                  <select
                    value={emailField}
                    onChange={(e) => setEmailField(e.target.value)}
                    className="w-full bg-[#0D0E12] border border-white/[0.08] px-2.5 py-1.5 rounded-md text-zinc-200 focus:outline-none focus:border-zinc-500 cursor-pointer"
                  >
                    <option value="">(Ninguna)</option>
                    {headers.map(h => <option key={h} value={h}>{h}</option>)}
                  </select>
                </div>

                <div>
                  <label className="block text-zinc-400 mb-1 font-medium text-[11px]">
                    Columna de Cargo
                  </label>
                  <select
                    value={cargoField}
                    onChange={(e) => setCargoField(e.target.value)}
                    className="w-full bg-[#0D0E12] border border-white/[0.08] px-2.5 py-1.5 rounded-md text-zinc-200 focus:outline-none focus:border-zinc-500 cursor-pointer"
                  >
                    <option value="">(Ninguna)</option>
                    {headers.map(h => <option key={h} value={h}>{h}</option>)}
                  </select>
                </div>
              </div>

              {/* Vista previa de los primeros 3 registros */}
              <div className="pt-2">
                <span className="text-[11px] text-zinc-400 block mb-1.5">
                  Vista previa de los primeros registros:
                </span>
                <div className="bg-[#0D0E12] border border-white/[0.06] rounded-lg overflow-x-auto text-[11px]">
                  <table className="w-full text-left">
                    <thead>
                      <tr className="border-b border-white/[0.06] text-zinc-400">
                        <th className="p-2">Nombre</th>
                        <th className="p-2">Institución</th>
                        <th className="p-2">Email</th>
                        <th className="p-2">Cargo</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-white/[0.04]">
                      {rawRows.slice(0, 3).map((r, i) => (
                        <tr key={i} className="text-zinc-300">
                          <td className="p-2 font-medium">{r[nameField] || <span className="text-zinc-600">-</span>}</td>
                          <td className="p-2">{r[instField] || <span className="text-zinc-600">-</span>}</td>
                          <td className="p-2 font-mono text-zinc-400">{r[emailField] || <span className="text-zinc-600">-</span>}</td>
                          <td className="p-2">{r[cargoField] || <span className="text-zinc-600">-</span>}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="p-4 border-t border-white/[0.06] flex justify-end gap-2 shrink-0">
          <button
            type="button"
            onClick={onClose}
            className="px-3 py-1.5 rounded-md bg-[#0D0E12] hover:bg-zinc-800 border border-white/[0.08] text-zinc-300 font-medium text-xs transition cursor-pointer"
          >
            Cancelar
          </button>
          <button
            type="button"
            onClick={handleImport}
            disabled={submitting || rawRows.length === 0 || !nameField}
            className="px-4 py-1.5 rounded-md bg-white hover:bg-zinc-200 text-zinc-950 font-medium text-xs shadow-sm transition cursor-pointer disabled:opacity-50"
          >
            {submitting ? 'Importando...' : `Importar ${rawRows.length} al Buzón`}
          </button>
        </div>
      </div>
    </div>
  );
}

