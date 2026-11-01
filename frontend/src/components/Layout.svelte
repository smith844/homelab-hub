<script>
  import Sidebar from "./Sidebar.svelte";
  import { siteName, theme } from "../lib/preferences.js";
  import { location } from "svelte-spa-router";
  $: document.title = `${$siteName || "Home Lab Hub"} · ${$location.startsWith("/map") ? "Maps" : $location.startsWith("/docs") ? "Documentation" : $location.startsWith("/settings") ? "Settings" : $location.startsWith("/inventory") ? "Inventory" : "Overview"}`;

  // In production (Docker), use relative URLs. In dev, use explicit URL for proxy.
  const API_BASE = import.meta.env.PROD ? '' : (import.meta.env.VITE_API_URL || 'http://localhost:5001');

  async function exportDatabase() {
    try {
      const response = await fetch(`${API_BASE}/inventory/export`, {
        method: 'GET',
        headers: {
          'Accept': 'application/json',
        }
      });
      
      if (!response.ok) {
        throw new Error(`HTTP error! status: ${response.status}`);
      }
      
      const data = await response.json();
      
      // Create a blob and download
      const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = 'homelab-export.json';
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
    } catch (error) {
      console.error('Export failed:', error);
      alert('Export failed: ' + error.message);
    }
  }

  async function importDatabase(event) {
    const file = event.target.files[0];
    if (!file) return;
    
    try {
      if (!confirm("Import replaces the existing inventory and documents. Have you saved an export?")) { event.target.value = ""; return; }
      const text = await file.text();
      const data = JSON.parse(text);
      
      const response = await fetch(`${API_BASE}/inventory/import`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify(data)
      });
      
      if (!response.ok) {
        throw new Error(`HTTP error! status: ${response.status}`);
      }
      
      alert('Import completed successfully!');
      window.location.reload();
    } catch (error) {
      console.error('Import failed:', error);
      alert('Import failed: ' + error.message);
    }
  }

  function triggerImport() {
    document.getElementById('import-file-input').click();
  }
</script>

<div class="layout">
  <header class="header">
    <a class="brand" href="#/"><img src="/favicon.svg" alt="" /><span><strong>{$siteName || "Home Lab Hub"}</strong><small>Infrastructure & knowledge</small></span></a>
    <div class="header-actions">
      <button class="theme-button" aria-label="Toggle light and dark theme" on:click={() => theme.set($theme === "dark" ? "light" : "dark")}>{$theme === "dark" ? "Light" : "Dark"}</button>
      <button class="btn btn-primary" on:click={exportDatabase}>Export Data</button>
      <button class="btn btn-secondary" on:click={triggerImport}>Import Data</button>
      <input id="import-file-input" type="file" accept=".json" style="display: none;" on:change={importDatabase} />
    </div>
  </header>
  
  <div class="content">
    <Sidebar />
    <main class="main">
      <slot />
    </main>
  </div>
</div>

<style>
  .brand{display:flex;align-items:center;gap:.7rem;text-decoration:none;color:white}.brand img{width:38px;height:38px}.brand strong{display:block;font-size:1rem;color:white;line-height:1.3}.brand small{display:block;font-size:.6rem;color:#adc3d1}.theme-button{background:transparent;border:1px solid #536879;color:white;margin:0;padding:.4rem .7rem;font-size:.75rem}.main{min-width:0}.header{min-height:76px}.header-actions{align-items:center}.brand:focus-visible{outline:2px solid #78d6cc}@media(max-width:760px){.content{flex-direction:column}.header{flex-wrap:wrap;gap:.6rem;padding:.7rem 1rem!important}.main{padding:1rem!important}.btn{font-size:.7rem!important}.brand small{display:none}}

  .layout {
    display: flex;
    flex-direction: column;
    min-height: 100vh;
  }
  
  .header {
    background-color: #102d42;
    color: white;
    padding: 1rem 1.5rem;
    display: flex;
    justify-content: space-between;
    align-items: center;
  }
  
  .header-actions {
    display: flex;
    gap: 0.5rem;
  }
  
  .btn {
    display: inline-block;
    padding: 0.5rem 1rem;
    border: none;
    border-radius: 4px;
    cursor: pointer;
    font-size: 0.9rem;
    font-weight: 500;
    line-height: 1.5;
    text-align: center;
    vertical-align: middle;
    box-sizing: border-box;
  }
  
  .btn-primary {
    background-color: #007bff;
    color: white;
  }
  
  .btn-primary:hover {
    background-color: #0056b3;
  }
  
  .btn-secondary {
    background-color: #6c757d;
    color: white;
  }
  
  .btn-secondary:hover {
    background-color: #545b62;
  }
  
  .content {
    display: flex;
    flex: 1;
  }
  
  .main {
    flex: 1;
    padding: 1.5rem;
    overflow-y: auto;
  }
</style>
