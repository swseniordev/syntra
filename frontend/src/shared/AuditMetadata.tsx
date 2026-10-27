import { useEffect, useState } from 'react';
import { api } from './api';

type Metadata = {
  creado_en?: string | null; creado_por?: number | null;
  actualizado_en?: string | null; actualizado_por?: number | null;
};

const dateTime = new Intl.DateTimeFormat('es-CO', {
  day: '2-digit', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit',
  hourCycle: 'h23', timeZone: 'America/Bogota',
});

export function AuditMetadata({ record, canViewUsers = false }: { record: Metadata; canViewUsers?: boolean }) {
  const [names, setNames] = useState<Record<number, string>>({});
  useEffect(() => {
    let live = true;
    setNames({});
    if (!canViewUsers) return () => { live = false; };
    const ids = [...new Set([record.creado_por, record.actualizado_por].filter((id): id is number => typeof id === 'number'))];
    void Promise.all(ids.map(async id => {
      try {
        const user = await (await api(`/usuarios/${id}`)).json() as { nombre?: string };
        return [id, user.nombre || ''] as const;
      } catch { return [id, ''] as const; }
    })).then(entries => { if (live) setNames(Object.fromEntries(entries)); });
    return () => { live = false; };
  }, [canViewUsers, record.creado_por, record.actualizado_por]);

  const user = (id?: number | null) => id == null ? 'No registrado' : names[id] || `Usuario #${id}`;
  const date = (value?: string | null) => value && !Number.isNaN(Date.parse(value))
    ? <time dateTime={value}>{dateTime.format(new Date(value))}</time> : 'Fecha no disponible';
  const updated = Boolean(record.actualizado_en && record.creado_en &&
    Date.parse(record.actualizado_en) > Date.parse(record.creado_en));
  return <p className="client-audit-foot">Creado por <b>{user(record.creado_por)}</b> · {date(record.creado_en)}<br />
    {updated ? <>Actualizado por <b>{user(record.actualizado_por)}</b> · {date(record.actualizado_en)}</> : 'Sin actualización registrada'}
  </p>;
}
