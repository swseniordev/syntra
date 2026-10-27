import '@testing-library/jest-dom/vitest';
import { configure } from '@testing-library/react';

// Las pantallas esperan 180 ms para búsquedas; el ejecutor paralelo puede tardar
// más de un segundo en CI antes de que termine la petición simulada.
configure({ asyncUtilTimeout: 3000 });
