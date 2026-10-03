import React from 'react';
import { createRoot } from 'react-dom/client';
import App, { ViewErrorBoundary } from './App';

createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <ViewErrorBoundary>
      <App />
    </ViewErrorBoundary>
  </React.StrictMode>
);
