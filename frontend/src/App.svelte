<script>
  import Router from "svelte-spa-router";
  import { wrap } from "svelte-spa-router/wrap";
  import Layout from "./components/Layout.svelte";
  import InventoryPage from "./pages/InventoryPage.svelte";
  import OverviewPage from "./pages/OverviewPage.svelte";
  import SettingsPage from "./pages/SettingsPage.svelte";
  import Toast from "./components/Toast.svelte";

  const routes = {
    "/": OverviewPage,
    "/settings": SettingsPage,
    "/inventory": InventoryPage,
    "/inventory/:type": InventoryPage,
    "/inventory/:type/:id": InventoryPage,
    "/map": wrap({ asyncComponent: () => import("./pages/MapPage.svelte") }),
    "/map/:root": wrap({ asyncComponent: () => import("./pages/MapPage.svelte") }),
    "/docs": wrap({ asyncComponent: () => import("./pages/DocsPage.svelte") }),
    "/docs/:id": wrap({ asyncComponent: () => import("./pages/DocsPage.svelte") }),
  };
</script>

<Layout>
  <Router {routes} />
</Layout>
<Toast />

<style>
  :global(body) {
    margin: 0;
    min-height: 100vh;
  }
  :global(#app) {
    min-height: 100vh;
  }
</style>
