import { useEffect, useState } from 'react';
import type { ChangeEvent, FormEvent } from 'react';
import { useNavigate } from 'react-router-dom';
import { Icon } from '../../shared/Icon';
import { EmptyState } from '../../shared/EmptyState';
import { api } from '../../shared/api';
import type { Cliente } from '../../shared/api';
import { useToast } from '../../shared/Toast';
import { PageHeading } from '../../shared/PageHeading';
import { previewMode } from '../../app/runtime';
import { clientError } from '../../shared/httpErrors';
type EntityFilter = { label: string; options: string[] };
type EntitySpec = { heading: string; description: string; create?: string; filters?: EntityFilter[]; columns: string[] };
export const ENTITY_SPECS: Record<string, EntitySpec> = {
  '/clientes': { heading: 'Clientes', description: 'Organizaciones para las que Syntra realiza escucha social. Cada cliente agrupa sus cuentas de monitoreo.', create: 'Nuevo cliente', filters: [{ label: 'Sector', options: [] }], columns: ['Cliente', 'Sector', 'Cuentas', 'Contacto'] },
  '/cuentas': { heading: 'Cuentas', description: 'Unidad de monitoreo de un cliente (marca, producto o tema). Define los prompts base de clusters y temas finales.', create: 'Nueva cuenta', filters: [{ label: 'Cliente', options: [] }], columns: ['Cuenta', 'Cliente', 'Grupos con acceso', 'Mediciones'] },
  '/prompts': { heading: 'Prompts por defecto', description: 'Plantillas base para clusters, temas finales, relevancia y sentimiento. Los de relevancia y sentimiento pueden ser específicos de una red social; en cada medición se ajustan por red.', create: 'Nuevo prompt', filters: [{ label: 'Tipo', options: ['Clusters', 'Temas finales', 'Relevancia', 'Sentimiento'] }, { label: 'Red', options: ['General (todas)', 'X', 'TikTok', 'YouTube', 'Facebook', 'Instagram', 'Medios y web'] }], columns: ['Prompt', 'Tipo', 'Red', 'Versión', 'Por defecto'] },
  '/regex': { heading: 'Regex', description: 'Condiciones para etiquetar registros, filtrarlos en fiscalización y registros, y preclasificarlos (preclustering) según el orden definido en cada medición. Al guardar se valida contra un texto de prueba.', create: 'Nueva regex', columns: ['Regex', 'Texto de prueba', 'Versión'] },
  '/paises': { heading: 'Países (Google News)', description: 'Países disponibles para las búsquedas de Google News en los procesos de scraping. El país define el portal (edición local) de Google News y el idioma de los resultados.', create: 'Nuevo país', columns: ['País', 'Idioma', 'Edición de Google News', 'Procesos que lo usan'] },
  '/usuarios': { heading: 'Usuarios', description: 'Personas con acceso a la plataforma. El rol define qué pueden hacer; los grupos definen qué cuentas pueden ver.', create: 'Nuevo usuario', filters: [{ label: 'Rol', options: [] }], columns: ['Usuario', 'Rol', 'Grupos', 'Cuentas visibles', 'Último acceso'] },
  '/roles': { heading: 'Roles y accesos', description: 'Matriz de permisos por módulo y acción. Los roles con acceso global ven todas las cuentas; los demás, solo las de sus grupos.', create: 'Nuevo rol', columns: ['Rol', 'Alcance', 'Permisos', 'Usuarios'] },
  '/grupos': { heading: 'Grupos de usuarios', description: 'Asocia usuarios con cuentas. Un usuario sin rol global solo verá las cuentas (y sus mediciones e informes) de sus grupos.', create: 'Nuevo grupo', columns: ['Grupo', 'Usuarios', 'Cuentas asociadas'] },
};
const modulesForPermissions = [['dashboard', 'Inicio'], ['clientes', 'Clientes'], ['cuentas', 'Cuentas'], ['usuarios', 'Usuarios'], ['roles', 'Roles y accesos'], ['grupos', 'Grupos de usuarios'], ['prompts', 'Prompts por defecto'], ['regex', 'Regex'], ['paises', 'Países (Google News)'], ['mediciones', 'Mediciones'], ['fiscalizacion', 'Fiscalización'], ['registros', 'Registros'], ['procesos', 'Procesos'], ['informes', 'Informes'], ['auditoria', 'Auditoría']];
const permissionActions = [['ver', 'Ver'], ['crear', 'Crear'], ['editar', 'Editar'], ['eliminar', 'Eliminar'], ['ejecutar', 'Ejecutar'], ['exportar', 'Exportar']];

export const ENTITY_STATES = [['vig', 'Vigentes'], ['act', 'Activos'], ['ina', 'Inactivos'], ['del', 'Eliminados']];
export const CREATION_ROUTES: Record<string, string> = { '/clientes': '/clientes/nuevo', '/cuentas': '/cuentas/nueva', '/prompts': '/prompts/nuevo', '/regex': '/regex/nueva', '/paises': '/paises/nuevo', '/usuarios': '/usuarios/nuevo', '/roles': '/roles/nuevo', '/grupos': '/grupos/nuevo' };
type CreationField = { name: string; label: string; type: 'text' | 'email' | 'number' | 'textarea' | 'select' | 'checkbox' | 'catalog'; required?: boolean; placeholder?: string; help?: string; options?: Array<[string, string]>; min?: number; max?: number; rows?: number; wide?: boolean; minLength?: number };
type CreationSpec = { title: string; description: string; fields: CreationField[]; special?: 'permissions' | 'group-pickers' };
const SECTOR_OPTIONS: Array<[string, string]> = ['Consultoría política', 'Gobierno estatal', 'Gobierno municipal', 'Partido político', 'Campaña electoral', 'Poder legislativo', 'Sociedad civil', 'Medios de comunicación', 'Otro'].map(value => [value, value]);
const STATE_OPTIONS: Array<[string, string]> = ['Aguascalientes', 'Baja California', 'Baja California Sur', 'Campeche', 'Chiapas', 'Chihuahua', 'Ciudad de México', 'Coahuila', 'Colima', 'Durango', 'Estado de México', 'Guanajuato', 'Guerrero', 'Hidalgo', 'Jalisco', 'Michoacán', 'Morelos', 'Nayarit', 'Nuevo León', 'Oaxaca', 'Puebla', 'Querétaro', 'Quintana Roo', 'San Luis Potosí', 'Sinaloa', 'Sonora', 'Tabasco', 'Tamaulipas', 'Tlaxcala', 'Veracruz', 'Yucatán', 'Zacatecas', 'México'].map(value => [value, value]);
const NETWORK_OPTIONS: Array<[string, string]> = [['x', 'X'], ['tiktok', 'TikTok'], ['youtube', 'YouTube'], ['facebook', 'Facebook'], ['instagram', 'Instagram'], ['medios', 'Medios y web']];
export const CREATION_SPECS: Record<string, CreationSpec> = {
  '/clientes': { title: 'Nuevo cliente', description: ENTITY_SPECS['/clientes'].description, fields: [
    { name: 'nombre', label: 'Nombre del cliente', type: 'text', required: true, placeholder: 'Ej. Ágora Consultores Políticos' }, { name: 'nit', label: 'RFC', type: 'text', placeholder: 'ABC123456XY0' }, { name: 'sector', label: 'Sector', type: 'select', options: SECTOR_OPTIONS }, { name: 'contacto', label: 'Correo de contacto', type: 'email', placeholder: 'contacto@cliente.mx' }, { name: 'estado', label: 'Estado', type: 'select', options: [['1', 'Activo'], ['0', 'Inactivo (borrador)']] },
  ] },
  '/cuentas': { title: 'Nueva cuenta', description: ENTITY_SPECS['/cuentas'].description, fields: [
    { name: 'nombre', label: 'Nombre de la cuenta', type: 'text', required: true, placeholder: 'Ej. Gob. Nuevo León · Nombre del gobernador' }, { name: 'cliente', label: 'Cliente asociado', type: 'catalog', required: true, help: 'Selecciona un cliente cuando exista el catálogo.' }, { name: 'marca', label: 'Actor o término principal', type: 'text', placeholder: 'Ej. el gobernador Salazar', help: 'Persona, institución o partido de referencia en el análisis.' }, { name: 'estadoFederal', label: 'Entidad federativa', type: 'select', options: STATE_OPTIONS }, { name: 'taxonomia', label: 'Taxonomía base', type: 'select', options: [['gobierno', 'Gobierno estatal'], ['comparativo', 'Comparativo de gobernadores'], ['electoral', 'Electoral / partidos']] }, { name: 'estado', label: 'Estado', type: 'select', options: [['1', 'Activo'], ['0', 'Inactivo (borrador)']] }, { name: 'promptClusters', label: 'Prompt de clusters', type: 'textarea', required: true, minLength: 20, rows: 5, wide: true, help: 'Prompt personalizado de esta cuenta.' }, { name: 'promptTemas', label: 'Prompt de temas finales', type: 'textarea', required: true, minLength: 20, rows: 5, wide: true, help: 'Prompt personalizado de esta cuenta.' },
  ] },
  '/prompts': { title: 'Nuevo prompt', description: ENTITY_SPECS['/prompts'].description, fields: [
    { name: 'nombre', label: 'Nombre', type: 'text', required: true }, { name: 'tipo', label: 'Tipo', type: 'select', required: true, options: [['cluster', 'Clusters'], ['temas', 'Temas finales'], ['relevancia', 'Relevancia'], ['sentimiento', 'Sentimiento']] }, { name: 'red', label: 'Red social', type: 'select', options: [['', 'General (todas las redes)'], ...NETWORK_OPTIONS], help: 'Los prompts de relevancia y sentimiento pueden tener un ajuste por red.' }, { name: 'estado', label: 'Estado', type: 'select', options: [['1', 'Activo'], ['0', 'Inactivo (borrador)']] }, { name: 'porDefecto', label: 'Usar como prompt por defecto de su tipo y red', type: 'checkbox', wide: true }, { name: 'contenido', label: 'Contenido del prompt', type: 'textarea', required: true, minLength: 20, rows: 12, wide: true, help: 'Mínimo 20 caracteres. Variables disponibles en el mockup: {{cuenta}}, {{num_clusters}}, {{num_subclusters}}, {{fecha_inicio}}, {{tipo_analisis}}, {{red}}.' },
  ] },
  '/regex': { title: 'Nueva regex', description: ENTITY_SPECS['/regex'].description, fields: [
    { name: 'nombre', label: 'Nombre', type: 'text', required: true, placeholder: 'Ej. Crisis del agua' }, { name: 'estado', label: 'Estado', type: 'select', options: [['1', 'Activo'], ['0', 'Inactivo (borrador)']] }, { name: 'condicion', label: 'Condición (expresión regular)', type: 'text', required: true, placeholder: String.raw`\b(agua|sequía|pipas?)\b`, help: 'La expresión se valida en este navegador y no se ejecuta sobre registros.' }, { name: 'ignorarMayusculas', label: 'Ignorar mayúsculas', type: 'checkbox' }, { name: 'prueba', label: 'Texto de prueba', type: 'textarea', required: true, rows: 3, wide: true, placeholder: 'Pega aquí un texto que la regex debe encontrar.' }, { name: 'descripcion', label: 'Descripción', type: 'text', wide: true, placeholder: 'Para qué sirve esta regex' },
  ] },
  '/paises': { title: 'Nuevo país', description: ENTITY_SPECS['/paises'].description, fields: [
    { name: 'nombre', label: 'Nombre del país', type: 'text', required: true, placeholder: 'Ej. México' }, { name: 'codigo', label: 'Código ISO (2 letras)', type: 'text', required: true, placeholder: 'MX', max: 2, help: 'ISO 3166-1 alfa-2. Define el portal de Google News.' }, { name: 'idioma', label: 'Idioma de los resultados', type: 'select', options: [['es-419', 'Español (Latinoamérica)'], ['es', 'Español (España)'], ['en-US', 'Inglés (EE. UU.)'], ['pt-BR', 'Portugués (Brasil)'], ['fr', 'Francés']] }, { name: 'estado', label: 'Estado', type: 'select', options: [['1', 'Activo'], ['0', 'Inactivo (borrador)']] },
  ] },
  '/usuarios': { title: 'Nuevo usuario', description: ENTITY_SPECS['/usuarios'].description, fields: [
    { name: 'nombre', label: 'Nombre completo', type: 'text', required: true }, { name: 'email', label: 'Correo corporativo', type: 'email', required: true }, { name: 'telefono', label: 'Teléfono', type: 'text', placeholder: '+57 300 000 0000' }, { name: 'rol', label: 'Rol', type: 'catalog', required: true, help: 'Los roles aparecerán cuando exista el catálogo correspondiente.' }, { name: 'estado', label: 'Estado', type: 'select', options: [['1', 'Activo'], ['0', 'Inactivo (borrador)']] }, { name: 'grupos', label: 'Grupos de usuarios', type: 'catalog', wide: true, help: 'Los grupos disponibles aparecerán cuando exista el catálogo correspondiente.' },
  ] },
  '/roles': { title: 'Nuevo rol', description: ENTITY_SPECS['/roles'].description, special: 'permissions', fields: [
    { name: 'nombre', label: 'Nombre del rol', type: 'text', required: true }, { name: 'estado', label: 'Estado', type: 'select', options: [['1', 'Activo'], ['0', 'Inactivo (borrador)']] }, { name: 'descripcion', label: 'Descripción', type: 'textarea', rows: 3, wide: true }, { name: 'verTodas', label: 'Acceso a todas las cuentas — ignora la restricción por grupos de usuarios', type: 'checkbox', wide: true }, { name: 'configCompleta', label: 'Configuración completa de mediciones — programación automática, prompts personalizados y criterios de bots', type: 'checkbox', wide: true },
  ] },
  '/grupos': { title: 'Nuevo grupo', description: ENTITY_SPECS['/grupos'].description, special: 'group-pickers', fields: [
    { name: 'nombre', label: 'Nombre del grupo', type: 'text', required: true }, { name: 'estado', label: 'Estado', type: 'select', options: [['1', 'Activo'], ['0', 'Inactivo (borrador)']] }, { name: 'descripcion', label: 'Descripción', type: 'textarea', rows: 3, wide: true },
  ] },
};

export function CreationFormPage({ path, editId }: { path: string; editId?: number }) {
  const navigate = useNavigate();
  const toast = useToast();
  const spec = CREATION_SPECS[path];
  const [values, setValues] = useState<Record<string, any>>({ estado: '1', estadoFederal: 'México', taxonomia: 'gobierno', idioma: 'es-419', tipo: 'cluster', red: '', sources: {}, permissions: {} });
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [dirty, setDirty] = useState(false);
  const [notice, setNotice] = useState('');
  const [confirmDiscard, setConfirmDiscard] = useState(false);
  const [etag, setEtag] = useState('');
  const [saving, setSaving] = useState(false);
  const clientLive = path === '/clientes' && !previewMode;
  const formTitle = editId ? 'Editar cliente' : spec?.title || 'Formulario';
  useEffect(() => {
    if (!clientLive || !editId) return;
    let live = true;
    api(`/clientes/${editId}`).then(async response => {
      const data: Cliente = await response.json();
      if (live) {
        setEtag(response.headers.get('ETag') || '');
        setValues({ nombre: data.nombre, nit: data.rfc || '', sector: data.sector || '', contacto: data.contacto || '', estado: String(data.estado_id) });
      }
    }).catch(error => { if (live) setNotice(error instanceof Error ? error.message : 'No se pudo cargar el cliente.'); });
    return () => { live = false; };
  }, [clientLive, editId]);
  if (!spec) return <PageHeading title="Formulario no disponible" />;
  const baseRoute = path;
  const update = (name: string, value: unknown) => { setDirty(true); setValues(current => ({ ...current, [name]: value })); setErrors(current => ({ ...current, [name]: '' })); setNotice(''); };
  const validate = () => {
    const next: Record<string, string> = {};
    for (const field of spec.fields) {
      const value = values[field.name];
      if (field.required && (typeof value !== 'string' || !value.trim())) next[field.name] = field.name === 'cliente' ? 'Selecciona el cliente' : field.name === 'rol' ? 'Selecciona un rol' : `${field.label} es obligatorio`;
      else if (field.type === 'email' && value && !/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(value)) next[field.name] = 'Correo no válido';
      else if (field.minLength && value && value.trim().length < field.minLength) next[field.name] = `Debe tener al menos ${field.minLength} caracteres`;
      else if (field.name === 'codigo' && value && !/^[a-z]{2}$/i.test(value)) next[field.name] = 'Ingresa un código ISO de dos letras';
    }
    if (path === '/regex' && values.condicion) {
      try { const regex = new RegExp(values.condicion, values.ignorarMayusculas ? 'i' : ''); if (values.prueba && !regex.test(values.prueba)) next.prueba = 'La expresión no coincide con el texto de prueba'; }
      catch (error) { next.condicion = `Expresión inválida: ${error instanceof Error ? error.message : 'revisa la sintaxis'}`; }
    }
    if (path === '/prompts' && values.porDefecto && values.estado === '0') next.estado = 'Un prompt por defecto debe estar activo';
    return next;
  };
  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (saving) return;
    const next = validate(); setErrors(next);
    if (Object.keys(next).length) { setNotice('Revisa los campos marcados. No se ha guardado información.'); if (clientLive) toast('Revisa los campos marcados', Object.values(next)[0], 'err'); return; }
    if (!clientLive) { setNotice('El guardado aún no está disponible. Tus datos siguen en este formulario y no se ha creado ningún registro.'); return; }
    const body = { nombre: String(values.nombre || '').trim(), rfc: String(values.nit || '').trim() || null, sector: String(values.sector || '').trim() || null, contacto: String(values.contacto || '').trim() || null, ...(!editId ? { estado_id: Number(values.estado || '1') } : {}) };
    setSaving(true);
    try {
      await api(editId ? `/clientes/${editId}` : '/clientes', { method: editId ? 'PATCH' : 'POST', headers: editId ? { 'If-Match': etag } : undefined, body: JSON.stringify(body) });
      toast(editId ? 'Cambios guardados' : 'Cliente creado', body.nombre);
      navigate(editId ? `/clientes/${editId}` : '/clientes');
    } catch (error) { toast('No se pudo guardar el cliente', clientError(error, 'Revisa los datos e inténtalo de nuevo.'), 'err'); }
    finally { setSaving(false); }
  };
  const cancel = () => { if (dirty) setConfirmDiscard(true); else navigate(`${baseRoute}${previewMode ? '?preview=1' : ''}`); };
  const renderField = (field: CreationField) => {
    const invalid = Boolean(errors[field.name]);
    const common = { id: `create-${field.name}`, name: field.name, value: values[field.name] ?? '', onChange: (event: ChangeEvent<HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement>) => update(field.name, event.target.value), 'aria-invalid': invalid, 'aria-describedby': invalid ? `create-${field.name}-error` : undefined };
    if (field.type === 'checkbox') return <label className={`create-check${field.wide ? ' span2' : ''}`} key={field.name}><input type="checkbox" checked={Boolean(values[field.name])} onChange={event => update(field.name, event.target.checked)} /><span>{field.label}</span></label>;
    if (field.type === 'catalog') return <div className={`field${field.wide ? ' span2' : ''}`} key={field.name}><label htmlFor={common.id}>{field.label}{field.required && <span className="required-mark"> *</span>}</label><select {...common} disabled><option value="">{field.name === 'cliente' ? 'Selecciona un cliente' : field.name === 'rol' ? 'Selecciona un rol' : 'No hay opciones disponibles'}</option></select>{field.help && <span className="field-help">{field.help}</span>}{invalid && <span id={`create-${field.name}-error`} className="field-error" role="alert">{errors[field.name]}</span>}</div>;
    return <div className={`field${field.wide ? ' span2' : ''}${invalid ? ' invalid' : ''}`} key={field.name}><label htmlFor={common.id}>{field.label}{field.required && <span className="required-mark"> *</span>}</label>{clientLive && field.name === 'sector' ? <input {...common} type="text" placeholder="Sector" /> : field.type === 'select' ? <select {...common}>{(field.options || []).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select> : field.type === 'textarea' ? <textarea {...common} rows={field.rows || 4} placeholder={field.placeholder} /> : <input {...common} type={field.type} placeholder={field.placeholder} min={field.min} max={field.max} maxLength={field.max} />}{field.help && <span className="field-help">{field.help}</span>}{invalid && <span id={`create-${field.name}-error`} className="field-error" role="alert">{errors[field.name]}</span>}</div>;
  };
  const setPermission = (module: string, action: string, enabled: boolean) => { setDirty(true); setValues(current => ({ ...current, permissions: { ...current.permissions, [`${module}:${action}`]: enabled } })); };
  return <>
    <PageHeading title={formTitle} description={spec.description} />
    <form className="panel creation-form" onSubmit={submit} noValidate>
      <div className="panel-heading"><h2>{formTitle}</h2><span className="panel-sub">Los campos con * son obligatorios</span></div>
      <div className="creation-form-body"><div className="form-grid">{spec.fields.filter(field => !(editId && field.name === 'estado') && !(path === '/prompts' && field.name === 'red' && !['relevancia', 'sentimiento'].includes(values.tipo))).map(renderField)}</div>
        {spec.special === 'permissions' && <section className="field span2 permission-section"><label>Permisos por módulo</label><p className="field-help">Selecciona los permisos que tendrá este rol. No se aplicarán hasta que exista persistencia.</p><div className="table-wrap permission-wrap"><table className="permission-table"><thead><tr><th>Módulo</th>{permissionActions.map(actionItem => <th key={actionItem[1]}>{actionItem[1]}</th>)}</tr></thead><tbody>{modulesForPermissions.map(moduleItem => <tr key={moduleItem[0]}><th scope="row">{moduleItem[1]}</th>{permissionActions.map(actionItem => <td key={actionItem[0]}><input type="checkbox" aria-label={`${moduleItem[1]}: ${actionItem[1]}`} checked={Boolean(values.permissions[`${moduleItem[0]}:${actionItem[0]}`])} onChange={event => setPermission(moduleItem[0], actionItem[0], event.target.checked)} /></td>)}</tr>)}</tbody></table></div></section>}
        {spec.special === 'group-pickers' && <div className="dual-picker span2"><section className="picklist"><div className="panel-heading"><h3>Usuarios</h3></div><EmptyState title="Sin usuarios disponibles" detail="Los usuarios aparecerán aquí cuando exista el catálogo correspondiente." /></section><section className="picklist"><div className="panel-heading"><h3>Cuentas</h3></div><EmptyState title="Sin cuentas disponibles" detail="Las cuentas aparecerán aquí cuando exista el catálogo correspondiente." /></section></div>}
        {path === '/usuarios' && <div className="form-note span2"><Icon name="info" size={16} /> El mockup contempla una invitación al usuario al guardar; no se enviará ningún correo en esta etapa.</div>}
        {path === '/regex' && values.condicion && values.prueba && !errors.condicion && !errors.prueba && <div className="regex-result span2" role="status">{(() => { try { return new RegExp(values.condicion, values.ignorarMayusculas ? 'i' : '').test(values.prueba) ? 'La expresión coincide con el texto de prueba.' : 'La expresión no coincide con el texto de prueba.'; } catch { return 'Expresión inválida.'; } })()}</div>}
        {notice && <p className={`control-notice span2${Object.keys(errors).length ? ' error' : ''}`} role="status">{notice}</p>}
      </div>
      <div className="form-actions creation-actions"><button type="button" className="button" onClick={cancel}><Icon name="arrow" size={15} /> Cancelar</button><button type="submit" className="button primary" disabled={saving}><Icon name="check" size={15} /> {saving ? 'Guardando…' : 'Guardar'}</button></div>
    </form>
    {confirmDiscard && <div className="command-scrim"><section className="command-panel discard-dialog" role="dialog" aria-modal="true" aria-labelledby="discard-form-title"><div className="panel-heading"><h2 id="discard-form-title">¿Descartar los cambios?</h2></div><p>Los datos escritos en este formulario se perderán y aún no se guardaron.</p><div className="form-actions"><button className="button" type="button" onClick={() => setConfirmDiscard(false)}>Conservar formulario</button><button className="button danger-button" type="button" onClick={() => navigate(`${baseRoute}${previewMode ? '?preview=1' : ''}`)}>Descartar y volver</button></div></section></div>}
  </>;
}

export function GenericModule({ path, title }: { path: string; title: string }) {
  const spec = ENTITY_SPECS[path];
  const [query, setQuery] = useState('');
  const [state, setState] = useState('vig');
  const [filters, setFilters] = useState<Record<string, string>>({});
  if (!spec) return <PageHeading title={title} />;
  const hasFilters = Boolean(query.trim() || Object.values(filters).some(Boolean) || state !== 'vig');
  return <>
    <PageHeading title={spec.heading} description={spec.description} action={spec.create ? { label: spec.create, icon: 'plus', path: CREATION_ROUTES[path] } : undefined} />
    <section className="panel entity-list-panel">
      <div className="module-toolbar entity-toolbar" aria-label={`Filtros de ${spec.heading}`}>
        <label className="search-field"><Icon name="search" size={16} /><input type="search" value={query} onChange={event => setQuery(event.target.value)} placeholder={`Buscar ${spec.heading.toLowerCase()}…`} aria-label={`Buscar ${spec.heading.toLowerCase()}`} /></label>
        {spec.filters?.map(filter => <select key={filter.label} aria-label={filter.label} value={filters[filter.label] ?? ''} onChange={event => setFilters(previous => ({ ...previous, [filter.label]: event.target.value }))}><option value="">{filter.label}: todos</option>{filter.options.map(option => <option key={option} value={option}>{option}</option>)}</select>)}
        <div className="seg status-segment" role="group" aria-label={`Filtrar ${spec.heading.toLowerCase()} por estado`}>{ENTITY_STATES.map(([key, label]) => <button type="button" key={key} className={state === key ? 'on' : ''} aria-pressed={state === key} onClick={() => setState(key)}>{label}<span className="n">—</span></button>)}</div>
      </div>
      <div className="table-wrap"><table className="data-table"><thead><tr>{[...spec.columns, 'Estado', 'Actualizado', 'Acciones'].map(column => <th key={column}>{column}</th>)}</tr></thead><tbody><tr><td colSpan={spec.columns.length + 3} className="empty-cell"><EmptyState title={hasFilters ? 'Sin resultados para los filtros' : `Aún no hay ${spec.heading.toLowerCase()}`} detail={query || Object.values(filters).some(Boolean) ? 'Prueba con otros criterios de búsqueda.' : 'El contenido aparecerá cuando haya información disponible.'} /></td></tr></tbody></table></div>
    </section>
  </>;
}
