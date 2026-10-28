import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import App from './App'
import { GaussianStudio } from './gaussian/GaussianStudio'
import { GaussianRigCheck } from './gaussian/GaussianRigCheck'
import './styles.css'

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    {window.location.pathname === '/gaussian/rig-check' ? <GaussianRigCheck /> : window.location.pathname.startsWith('/gaussian') ? <GaussianStudio /> : <App />}
  </StrictMode>,
)
