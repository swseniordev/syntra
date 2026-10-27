import { Route, Routes } from 'react-router-dom';
import type { Yo } from '../shared/api';
import { navigation } from '../shared/navigation';
import { previewMode } from './runtime';
import { CREATION_ROUTES, CreationFormPage, GenericModule } from '../modules/general/GenericEntityModule';
import { HomePage } from '../modules/inicio/HomePage';
import { MeasurementsPage, NewMeasurementPage, MeasurementSourceConfigPage, MeasurementDetail } from '../modules/mediciones/MeasurementModule';
import { ProcessesPage } from '../modules/procesos/ProcessesPage';
import { AuditList, AuditDetail } from '../modules/auditoria/AuditModule';
import { AuditPage } from '../modules/auditoria/AuditPreviewPage';
import { ClientsPage, ClientDetail, ClientEditRoute } from '../modules/clientes/ClientsModule';
import { RoleDetail, RoleForm, RolesList } from '../modules/roles/RolesModule';
import { CountriesList, CountryDetail, CountryForm } from '../modules/paises/CountriesModule';
import { PromptsList, PromptDetail, PromptForm } from '../modules/prompts/PromptsModule';
import { RegexList, RegexDetail, RegexForm } from '../modules/regex/RegexModule';
import { AccountsList, AccountDetail, AccountForm } from '../modules/cuentas/AccountsModule';
import { GroupsList, GroupDetail, GroupForm } from '../modules/grupos/GroupsModule';
import { UsersList, UserDetail, UserForm } from '../modules/usuarios/UsersModule';
import { EmptyState } from '../shared/EmptyState';

export function AppRoutes({ yo, onOpenSearch }: { yo: Yo | null; onOpenSearch: () => void }) {
  return <Routes>
    <Route path="/" element={<HomePage onOpenSearch={onOpenSearch} />} />
    <Route path="/mediciones" element={<MeasurementsPage />} />
    <Route path="/mediciones/nueva" element={<NewMeasurementPage yo={yo || null} />} />
    <Route path="/mediciones/:id/editar" element={<MeasurementSourceConfigPage yo={yo || null} />} />
    {Object.entries(CREATION_ROUTES).filter(([path]) => previewMode || !['/roles', '/paises', '/prompts', '/regex', '/cuentas', '/grupos', '/usuarios'].includes(path)).map(([path, route]) => <Route key={route} path={route} element={<CreationFormPage path={path} />} />)}
    <Route path="/mediciones/:id/*" element={<MeasurementDetail yo={yo || null} />} />
    <Route path="/procesos" element={<ProcessesPage yo={yo || null} />} />
    <Route path="/auditoria" element={previewMode ? <AuditPage /> : <AuditList yo={yo || null} />} />
    {!previewMode && <Route path="/auditoria/:id" element={<AuditDetail />} />}
    {!previewMode && <><Route path="/clientes" element={<ClientsPage yo={yo || null} />} /><Route path="/clientes/:id" element={<ClientDetail yo={yo || null} />} /><Route path="/clientes/:id/editar" element={<ClientEditRoute />} /></>}
    {!previewMode && <><Route path="/roles" element={<RolesList yo={yo || null} />} /><Route path="/roles/nuevo" element={<RoleForm yo={yo || null} />} /><Route path="/roles/:id/editar" element={<RoleForm yo={yo || null} />} /><Route path="/roles/:id" element={<RoleDetail yo={yo || null} />} /></>}
    {!previewMode && <><Route path="/paises" element={<CountriesList yo={yo || null} />} /><Route path="/paises/nuevo" element={<CountryForm />} /><Route path="/paises/:id/editar" element={<CountryForm />} /><Route path="/paises/:id" element={<CountryDetail yo={yo || null} />} /></>}
    {!previewMode && <><Route path="/prompts" element={<PromptsList yo={yo || null} />} /><Route path="/prompts/nuevo" element={<PromptForm />} /><Route path="/prompts/:id/editar" element={<PromptForm />} /><Route path="/prompts/:id" element={<PromptDetail yo={yo || null} />} /></>}
    {!previewMode && <><Route path="/regex" element={<RegexList yo={yo || null} />} /><Route path="/regex/nueva" element={<RegexForm />} /><Route path="/regex/:id/editar" element={<RegexForm />} /><Route path="/regex/:id" element={<RegexDetail yo={yo || null} />} /></>}
    {!previewMode && <><Route path="/cuentas" element={<AccountsList yo={yo || null} />} /><Route path="/cuentas/nueva" element={<AccountForm />} /><Route path="/cuentas/:id/editar" element={<AccountForm />} /><Route path="/cuentas/:id" element={<AccountDetail yo={yo || null} />} /></>}
    {!previewMode && <><Route path="/grupos" element={<GroupsList yo={yo || null} />} /><Route path="/grupos/nuevo" element={<GroupForm />} /><Route path="/grupos/:id/editar" element={<GroupForm />} /><Route path="/grupos/:id" element={<GroupDetail yo={yo || null} />} /></>}
    {!previewMode && <><Route path="/usuarios" element={<UsersList yo={yo || null} />} /><Route path="/usuarios/nuevo" element={<UserForm yo={yo || null} />} /><Route path="/usuarios/:id/editar" element={<UserForm yo={yo || null} />} /><Route path="/usuarios/:id" element={<UserDetail yo={yo || null} />} /></>}
    {navigation.flatMap(group => group.items).filter(item => !['/', '/mediciones', '/procesos', '/auditoria'].includes(item.path) && (previewMode || !['/clientes', '/roles', '/paises', '/prompts', '/regex', '/cuentas', '/grupos', '/usuarios'].includes(item.path))).map(item => <Route key={item.path} path={item.path} element={<GenericModule path={item.path} title={item.label} />} />)}
    <Route path="*" element={<section className="panel"><EmptyState title="Página no encontrada" detail="La ruta solicitada no forma parte de las vistas visuales incluidas." /></section>} />
  </Routes>;
}