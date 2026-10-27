import { Icon } from '../shared/Icon';

export const loadOptionDefinitions = [
  ['incorporar', 'Incorporar automáticamente', 'Si es «No», los datos pasan por fiscalización', 'zap'],
  ['relevancia', 'Evaluar relevancia', 'La IA marca si cumple los criterios configurados', 'pulse'],
  ['sentimiento', 'Evaluar sentimiento', 'Clasifica el tono al incorporarse', 'sparkles'],
  ['clusters', 'Generar clusters', 'Genera clusters, subclusters y temas', 'layers'],
  ['bots', 'Análisis de bots', 'Marca cuentas automatizadas', 'bot'],
] as const;

export type LoadAction = typeof loadOptionDefinitions[number][0];

export function LoadActionSelector({ value, onChange, caption, disabled = false }: {
  value: Record<string, boolean>;
  onChange: (key: LoadAction, enabled: boolean) => void;
  caption: string;
  disabled?: boolean;
}) {
  return <div className="measurement-on-load">
    <span className="measurement-on-load-caption"><Icon name="zap" size={15} /> {caption}</span>
    <div className="measurement-on-load-grid">{loadOptionDefinitions.map(([key, label, description, icon]) => {
      const enabled = Boolean(value[key]);
      return <div className={`measurement-load-card${enabled ? ' selected' : ''}`} key={key}>
        <span className="measurement-load-icon"><Icon name={icon} size={17} /></span>
        <span><b>{label}</b><small>{description}</small></span>
        <div className="seg" role="group" aria-label={label}>
          <button type="button" className={enabled ? 'on' : ''} aria-pressed={enabled} disabled={disabled}
            onClick={() => onChange(key, true)}>Sí</button>
          <button type="button" className={!enabled ? 'on' : ''} aria-pressed={!enabled} disabled={disabled}
            onClick={() => onChange(key, false)}>No</button>
        </div>
      </div>;
    })}</div>
  </div>;
}
