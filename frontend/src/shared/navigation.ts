export type NavigationItem = {
  label: string;
  path: string;
  icon: string;
};

export const navigation = [
  {
    group: 'Análisis',
    items: [
      { label: 'Inicio', path: '/', icon: 'home' },
      { label: 'Mediciones', path: '/mediciones', icon: 'pulse' },
      { label: 'Monitor de procesos', path: '/procesos', icon: 'cycle' },
    ],
  },
  {
    group: 'Configuración',
    items: [
      { label: 'Clientes', path: '/clientes', icon: 'building' },
      { label: 'Cuentas', path: '/cuentas', icon: 'briefcase' },
      { label: 'Prompts por defecto', path: '/prompts', icon: 'sparkles' },
      { label: 'Regex', path: '/regex', icon: 'code' },
      { label: 'Países', path: '/paises', icon: 'globe' },
    ],
  },
  {
    group: 'Seguridad',
    items: [
      { label: 'Usuarios', path: '/usuarios', icon: 'user' },
      { label: 'Roles y accesos', path: '/roles', icon: 'shield' },
      { label: 'Grupos de usuarios', path: '/grupos', icon: 'layers' },
      { label: 'Auditoría', path: '/auditoria', icon: 'scroll' },
    ],
  },
] satisfies { group: string; items: NavigationItem[] }[];

export const routeLabels = Object.fromEntries(
  navigation.flatMap(({ items }) => items.map(({ path, label }) => [path, label])),
);
