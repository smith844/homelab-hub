<script>
  import { onMount } from "svelte";
  import GroupIcon from "../components/GroupIcon.svelte";
  const previewValue = (value) => value === undefined || value === null ? "(empty)" : typeof value === "object" ? JSON.stringify(value, null, 2) : String(value);
  import { get, post, put, del } from "../lib/api.js";
  import { addToast } from "../lib/stores.js";
  import { adminHeaders, getAdminToken, setAdminToken } from "../lib/admin.js";

  let data = { hosts: [], groups: [], apps: [], unmatched: [] };
  let loading = true;
  let error = "";
  let busy = false;
  let selectedHost = "*";
  let syncHost = "";
  let token = getAdminToken();
  let newGroup = { name: "", host: "", color: "#126e77", icon: "", sort_order: 0 };
  let editingId = null;
  let editForm = { name: "", color: "", icon: "", sort_order: 0 };
  let syncReport = null;
  let syncError = "";

  async function load() {
    loading = true;
    error = "";
    try {
      data = await get("/container-groups/management");
      const creatable = data.hosts.filter((host) => host.key);
      if (!newGroup.host && creatable.length) newGroup.host = creatable[0].key;
      if (!syncHost && creatable.length) syncHost = creatable[0].key;
      if (editingId && !data.groups.some((group) => group.id === editingId)) editingId = null;
    } catch (e) {
      error = e.message;
    } finally {
      loading = false;
    }
  }

  onMount(load);

  $: canWrite = Boolean(token.trim());
  $: creatableHosts = data.hosts.filter((host) => host.key);
  $: visibleGroups = selectedHost === "*"
    ? data.groups
    : data.groups.filter((group) => group.host_key === selectedHost);
  $: groupSections = data.hosts
    .map((host) => ({
      host,
      groups: visibleGroups.filter((group) => group.host_key === host.key),
    }))
    .filter((section) => section.groups.length || selectedHost === section.host.key);
  $: visibleApps = selectedHost === "*"
    ? data.apps
    : data.apps.filter((app) => app.host_key === selectedHost);
  $: visibleUnmatched = selectedHost === "*"
    ? data.unmatched
    : data.unmatched.filter((item) => item.host_key === selectedHost);
  $: ungroupedApps = visibleApps.filter((app) => app.group_id === null);

  function hostLabel(key) {
    return data.hosts.find((host) => host.key === key)?.label || (key || "No host");
  }

  function groupsForHost(hostKey) {
    return data.groups.filter(
      (group) => group.active && (group.host_key === hostKey || !group.host_key)
    );
  }

  function selectHost(value) {
    selectedHost = value;
    if (value !== "*") newGroup.host = value;
  }

  function saveToken() {
    setAdminToken(token.trim());
    addToast(token.trim() ? "Admin token saved for this session" : "Admin token cleared", "success");
  }

  function requireToken() {
    if (!token.trim()) {
      addToast("Enter and save the admin token before making changes", "error");
      return false;
    }
    return true;
  }

  async function createGroup() {
    if (!requireToken()) return;
    busy = true;
    try {
      await post(
        "/container-groups",
        {
          name: newGroup.name,
          host_key: newGroup.host,
          color: newGroup.color || null,
          icon: newGroup.icon || null,
          sort_order: Number(newGroup.sort_order) || 0,
        },
        { headers: adminHeaders() }
      );
      newGroup.name = "";
      newGroup.icon = "";
      await load();
      addToast("Group created", "success");
    } catch (e) {
      addToast(e.message, "error");
    } finally {
      busy = false;
    }
  }

  function startEdit(group) {
    editingId = group.id;
    editForm = {
      name: group.name,
      color: group.color || "",
      icon: group.icon || "",
      sort_order: group.sort_order,
    };
  }

  async function saveEdit(group) {
    if (!requireToken()) return;
    busy = true;
    try {
      const payload = {
        color: editForm.color || null,
        icon: editForm.icon || null,
        sort_order: Number(editForm.sort_order) || 0,
      };
      if (group.source === "manual") payload.name = editForm.name;
      // Saving a colour change must not pin unchanged imported icon/order fields.
      for (const field of Object.keys(payload)) {
        if (payload[field] === (group[field] ?? null)) delete payload[field];
      }
      await put(`/container-groups/${group.id}`, payload, { headers: adminHeaders() });
      editingId = null;
      await load();
      addToast("Group updated", "success");
    } catch (e) {
      addToast(e.message, "error");
    } finally {
      busy = false;
    }
  }

  async function toggleActive(group) {
    if (!requireToken()) return;
    if (!confirm(`${group.active ? "Archive" : "Restore"} the group “${group.name}”?`)) return;
    busy = true;
    try {
      await put(
        `/container-groups/${group.id}`,
        { active: !group.active },
        { headers: adminHeaders() }
      );
      await load();
      addToast(group.active ? "Group archived" : "Group restored", "success");
    } catch (e) {
      addToast(e.message, "error");
    } finally {
      busy = false;
    }
  }

  async function removeGroup(group) {
    if (!requireToken()) return;
    if (!confirm(`Delete the group “${group.name}”? This cannot be undone.`)) return;
    busy = true;
    try {
      await del(`/container-groups/${group.id}`, undefined, { headers: adminHeaders() });
      await load();
      addToast("Group deleted", "success");
    } catch (e) {
      addToast(e.message, "error");
    } finally {
      busy = false;
    }
  }

  async function assignApp(app, value) {
    if (!requireToken()) return;
    busy = true;
    try {
      await put(
        "/container-groups/assignments",
        { app_id: app.app_id, group_id: value === "" ? null : Number(value) },
        { headers: adminHeaders() }
      );
      await load();
      addToast("Assignment saved", "success");
    } catch (e) {
      addToast(e.message, "error");
    } finally {
      busy = false;
    }
  }

  async function revertApp(app) {
    if (!requireToken()) return;
    busy = true;
    try {
      await del(
        "/container-groups/assignments",
        { app_id: app.app_id },
        { headers: adminHeaders() }
      );
      await load();
      addToast("Reverted to imported assignment", "success");
    } catch (e) {
      addToast(e.message, "error");
    } finally {
      busy = false;
    }
  }

  function assignmentLabel(app) {
    if (app.explicit_ungrouped) return "Manually ungrouped";
    if (app.match === "override") return "Manual override";
    if (app.match === "assignment") return "FolderView";
    return "Ungrouped";
  }

  async function syncFolderview(dryRun) {
    if (!requireToken()) return;
    if (!syncHost) {
      addToast("Choose a host for the FolderView sync", "error");
      return;
    }
    if (!dryRun && !confirm("Apply the FolderView sync? Manual overrides will be preserved.")) return;
    busy = true;
    syncError = "";
    syncReport = null;
    try {
      syncReport = await post(
        "/container-groups/sync",
        { host_key: syncHost, dry_run: dryRun },
        { headers: adminHeaders() }
      );
      if (!dryRun) {
        await load();
        addToast("FolderView sync applied", "success");
      }
    } catch (e) {
      syncError = e.message;
      addToast(e.message, "error");
    } finally {
      busy = false;
    }
  }
</script>

<section class="groups-page">
  <div class="eyebrow">CONTAINER INVENTORY</div>
  <h1>Container groups</h1>
  <p class="intro">
    Manage Docker categories, manual overrides and FolderView Plus synchronisation. Imported
    FolderView assignments stay intact; manual choices always win.
  </p>

  <article class="access-card">
    <h2>Administrative access</h2>
    <p>
      Write operations require the server to be configured with
      <code>HLH_ADMIN_TOKEN</code>. The token is kept in this browser session only.
    </p>
    <div class="token-row">
      <input type="password" bind:value={token} placeholder="Administrative token" aria-label="Administrative token" />
      <button class="secondary outline" on:click={saveToken}>Save token</button>
    </div>
    <p class:writable={canWrite} class="token-status">
      {canWrite ? "Writes enabled for this browser session." : "Writes are disabled until a token is saved."}
    </p>
  </article>

  {#if error}
    <p role="alert">{error}</p>
  {:else if loading}
    <p aria-busy="true">Loading groups…</p>
  {:else}
    <div class="toolbar-row">
      <label>
        Host
        <select bind:value={selectedHost} on:change={(event) => selectHost(event.target.value)}>
          <option value="*">All hosts</option>
          {#each data.hosts as host}
            <option value={host.key}>{host.label}</option>
          {/each}
        </select>
      </label>
      <span class="muted">{visibleApps.length} applications · {visibleGroups.length} groups</span>
    </div>

    <article class="create-card">
      <h2>Create a manual group</h2>
      <div class="create-grid">
        <label>Name<input type="text" bind:value={newGroup.name} maxlength="80" placeholder="e.g. Local AI" /></label>
        <label>
          Host
          <select bind:value={newGroup.host}>
            {#each creatableHosts as host}
              <option value={host.key}>{host.label}</option>
            {/each}
          </select>
        </label>
        <label>Colour<input type="color" bind:value={newGroup.color} /></label>
        <label>Icon<input type="text" bind:value={newGroup.icon} maxlength="100000" placeholder="Image URL or emoji" /></label>
        <label>Sort<input type="number" bind:value={newGroup.sort_order} /></label>
        <button on:click={createGroup} disabled={busy || !canWrite}>Create group</button>
      </div>
    </article>

    {#each groupSections as section (section.host.key)}
      <section class="host-section">
        <div class="section-heading">
          <h2>{section.host.label}</h2>
          <span class="muted">{section.groups.length} groups</span>
        </div>
        <div class="table-scroll">
          <table class="data-table">
            <thead>
              <tr>
                <th>Group</th>
                <th>Source</th>
                <th>Members</th>
                <th>Status</th>
                <th class="actions-col">Actions</th>
              </tr>
            </thead>
            <tbody>
              {#each section.groups as group (group.id)}
                <tr class:archived={!group.active}>
                  <td>
                    <span class="color-dot" style={`background:${group.color || "transparent"}`}></span>
                    <GroupIcon value={group.icon} />
                    <strong>{group.name}</strong>
                  </td>
                  <td>
                    <span class="badge" class:manual={group.source === "manual"} class:imported={group.source !== "manual"}>
                      {group.source === "manual" ? "Manual" : "FolderView"}
                    </span>
                  </td>
                  <td class="counts">
                    {group.assignment_count} imported · {group.override_count} manual
                    {#if group.unmatched_count}· {group.unmatched_count} missing{/if}
                  </td>
                  <td>{group.active ? "Active" : "Archived"}</td>
                  <td class="group-actions">
                    <button class="secondary outline small" on:click={() => startEdit(group)}>Edit</button>
                    <button class="secondary outline small" on:click={() => toggleActive(group)} disabled={busy || !canWrite}>
                      {group.active ? "Archive" : "Restore"}
                    </button>
                    {#if group.source === "manual"}
                      <button class="secondary outline small" on:click={() => removeGroup(group)} disabled={busy || !canWrite}>
                        Delete
                      </button>
                    {/if}
                  </td>
                </tr>
                {#if editingId === group.id}
                  <tr>
                    <td colspan="5">
                      <div class="edit-grid">
                        <label>
                          Name
                          <input type="text" bind:value={editForm.name} disabled={group.source !== "manual"} maxlength="80" />
                          {#if group.source !== "manual"}<small>Imported names are managed by FolderView.</small>{/if}
                        </label>
                        <label>Colour<input type="color" bind:value={editForm.color} /></label>
                        <label>Icon<input type="text" bind:value={editForm.icon} maxlength="100000" placeholder="Image URL or emoji" /></label>
                        <label>Sort<input type="number" bind:value={editForm.sort_order} /></label>
                        <div class="edit-actions">
                          <button on:click={() => saveEdit(group)} disabled={busy || !canWrite}>Save</button>
                          <button class="secondary outline" on:click={() => (editingId = null)}>Cancel</button>
                        </div>
                      </div>
                    </td>
                  </tr>
                {/if}
              {/each}
              {#if !section.groups.length}
                <tr><td colspan="5" class="muted">No groups for this host yet.</td></tr>
              {/if}
            </tbody>
          </table>
        </div>
      </section>
    {/each}

    <article class="ungrouped-card">
      <h2>Ungrouped</h2>
      <p>{ungroupedApps.length} applications without an effective group.</p>
      {#if ungroupedApps.length}
        <ul class="chip-list">
          {#each ungroupedApps as app (app.app_id)}
            <li>{app.name}</li>
          {/each}
        </ul>
      {/if}
    </article>

    <section class="host-section">
      <div class="section-heading">
        <h2>Applications and assignments</h2>
        <span class="muted">Manual overrides take precedence over FolderView.</span>
      </div>
      <div class="table-scroll">
        <table class="data-table">
          <thead>
            <tr>
              <th>Application</th>
              <th>Host</th>
              <th>Effective group</th>
              <th>Source</th>
              <th>Imported</th>
              <th class="actions-col">Actions</th>
            </tr>
          </thead>
          <tbody>
            {#each visibleApps as app (app.app_id)}
              <tr>
                <td>
                  <strong>{app.name}</strong>
                  <small class="muted block">{app.container_key}</small>
                </td>
                <td>{app.host_label || "No host"}</td>
                <td>
                  <select
                    value={app.group_id === null ? "" : String(app.group_id)}
                    on:change={(event) => assignApp(app, event.target.value)}
                    disabled={busy || !canWrite}
                    aria-label={`Effective group for ${app.name}`}
                  >
                    <option value="">Ungrouped</option>
                    {#each groupsForHost(app.host_key) as group}
                      <option value={String(group.id)}>{group.name}</option>
                    {/each}
                  </select>
                </td>
                <td>{assignmentLabel(app)}</td>
                <td>{app.imported_group_name || "—"}</td>
                <td>
                  {#if app.override}
                    <button class="secondary outline small" on:click={() => revertApp(app)} disabled={busy || !canWrite}>
                      Revert
                    </button>
                  {/if}
                </td>
              </tr>
            {/each}
            {#if !visibleApps.length}
              <tr><td colspan="6" class="muted">No applications for this host.</td></tr>
            {/if}
          </tbody>
        </table>
      </div>
    </section>

    <section class="host-section">
      <div class="section-heading">
        <h2>Unmatched FolderView memberships</h2>
        <span class="muted">Assigned containers that are not in the discovered inventory.</span>
      </div>
      <div class="table-scroll">
        <table class="data-table">
          <thead>
            <tr><th>Container</th><th>Group</th><th>Host</th><th>Source</th></tr>
          </thead>
          <tbody>
            {#each visibleUnmatched as item (item.group_id + "|" + item.host_key + "|" + item.container_key)}
              <tr>
                <td>{item.container_label}<small class="muted block">{item.container_key}</small></td>
                <td>{item.group_name}</td>
                <td>{item.host_label || hostLabel(item.host_key)}</td>
                <td>{item.match === "override" ? "Manual override" : "FolderView"}</td>
              </tr>
            {/each}
            {#if !visibleUnmatched.length}
              <tr><td colspan="4" class="muted">No unmatched memberships.</td></tr>
            {/if}
          </tbody>
        </table>
      </div>
    </section>

    <article class="sync-card">
      <h2>FolderView Plus synchronisation</h2>
      <p>
        Refresh imported groups from the read-only FolderView configuration. Manual overrides are
        preserved, unmatched memberships are reported, and nothing is written back to Unraid.
      </p>
      <div class="sync-controls">
        <label>
          Host
          <select bind:value={syncHost}>
            {#each creatableHosts as host}
              <option value={host.key}>{host.label}</option>
            {/each}
          </select>
        </label>
        <button class="secondary outline" on:click={() => syncFolderview(true)} disabled={busy || !canWrite}>
          Preview sync
        </button>
        <button on:click={() => syncFolderview(false)} disabled={busy || !canWrite}>Apply sync</button>
      </div>
      {#if syncError}<p role="alert">{syncError}</p>{/if}
      {#if syncReport}
        <div class="sync-report" aria-live="polite">
          <p><strong>{syncReport.dry_run ? "Preview" : "Applied"}</strong> · {syncReport.folders.total} folders</p>
          <ul>
            <li>Groups: {syncReport.groups.created} created, {syncReport.groups.updated} updated, {syncReport.groups.reactivated} reactivated, {syncReport.groups.unchanged} unchanged, {syncReport.groups.archived} archived</li>
            <li>Assignments: {syncReport.assignments.added} added, {syncReport.assignments.moved} moved, {syncReport.assignments.removed} removed, {syncReport.assignments.unchanged} unchanged</li>
            <li>Manual overrides untouched: {syncReport.overrides.untouched}</li>
          </ul>
          <h3>Group changes</h3>
          <p>Source metadata records the FolderView snapshot. Local icons, ordering, colours and archive choices are preserved.</p>
          {#each syncReport.group_changes || [] as change}
            <details open>
              <summary>{change.name} ({change.external_id}) — {change.action}</summary>
              <div class="table-scroll">
                <table class="data-table change-table">
                  <thead><tr><th>Field</th><th>Before</th><th>After</th></tr></thead>
                  <tbody>
                    {#each change.fields as field}
                      <tr><td>{field.field}</td><td><pre>{field.before_present === false ? "(absent)" : previewValue(field.before)}</pre></td><td><pre>{field.after_present === false ? "(absent)" : previewValue(field.after)}</pre></td></tr>
                    {/each}
                  </tbody>
                </table>
              </div>
              {#each change.preserved as field}
                <p><strong>{field.field} — local choice preserved.</strong> Local: {previewValue(field.local)} · FolderView: {previewValue(field.incoming)}</p>
              {/each}
            </details>
          {:else}
            <p>No group field changes.</p>
          {/each}
          {#if syncReport.conflicts.length}
            <p><strong>Conflicts:</strong> {syncReport.conflicts.length}</p>
          {/if}
          {#if syncReport.warnings.length}
            <p><strong>Warnings:</strong> {syncReport.warnings.join(" · ")}</p>
          {/if}
          {#if syncReport.unmatched_containers.length}
            <p><strong>Unmatched containers:</strong> {syncReport.unmatched_containers.join(", ")}</p>
          {/if}
          {#if syncReport.ungrouped_apps.length}
            <p><strong>Ungrouped applications:</strong> {syncReport.ungrouped_apps.join(", ")}</p>
          {/if}
        </div>
      {/if}
    </article>
  {/if}
</section>

<style>
  .groups-page { max-width: 1280px; }
  .eyebrow { font-size: .7rem; font-weight: 750; letter-spacing: .13em; color: var(--pico-primary); }
  .groups-page h1 { margin: .4rem 0; letter-spacing: -.03em; }
  .intro { max-width: 780px; color: var(--pico-muted-color); font-size: .9rem; margin-bottom: 1.4rem; }
  .access-card, .create-card, .sync-card, .ungrouped-card { border: 1px solid var(--pico-muted-border-color); box-shadow: none; border-radius: 12px; }
  .access-card h2, .create-card h2, .sync-card h2, .ungrouped-card h2 { font-size: 1.05rem; }
  .access-card p, .sync-card p, .ungrouped-card p { font-size: .82rem; color: var(--pico-muted-color); }
  .token-row { display: flex; flex-wrap: wrap; gap: .5rem; }
  .token-row input { flex: 1 1 260px; margin: 0; height: 2.5rem; }
  .token-row button { margin: 0; height: 2.5rem; }
  .token-status { margin: .6rem 0 0; }
  .token-status.writable { color: var(--pico-primary); }
  .toolbar-row { display: flex; flex-wrap: wrap; align-items: center; justify-content: space-between; gap: 1rem; margin: 1.2rem 0 .8rem; }
  .toolbar-row label { margin: 0; font-size: .75rem; }
  .toolbar-row select { margin: .3rem 0 0; }
  .muted { color: var(--pico-muted-color); font-size: .75rem; }
  .block { display: block; }
  .create-grid, .edit-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr)); gap: .7rem; align-items: end; }
  .create-grid label, .edit-grid label { margin: 0; font-size: .72rem; }
  .create-grid input, .edit-grid input { margin: .25rem 0 0; height: 2.4rem; }
  .create-grid button, .edit-actions button { margin: 0; height: 2.4rem; }
  .edit-actions { display: flex; gap: .5rem; }
  .host-section { margin: 1.4rem 0; }
  .section-heading { display: flex; align-items: baseline; justify-content: space-between; gap: 1rem; }
  .section-heading h2 { font-size: 1.15rem; margin: 0 0 .4rem; }
  .table-scroll { overflow-x: auto; border: 1px solid var(--pico-muted-border-color); border-radius: 12px; }
  .data-table { margin: 0; min-width: 720px; }
  .data-table th { font-size: .68rem; text-transform: uppercase; letter-spacing: .06em; color: var(--pico-muted-color); }
  .data-table td { font-size: .8rem; vertical-align: middle; }
  .data-table tr.archived td { opacity: .65; }
  .actions-col { width: 1%; white-space: nowrap; }
  .group-actions { display: flex; flex-wrap: wrap; gap: .35rem; }
  .group-actions button { margin: 0; padding: .25rem .5rem; font-size: .68rem; }
  .counts { white-space: nowrap; }
  .color-dot { display: inline-block; width: 10px; height: 10px; border-radius: 50%; border: 1px solid var(--pico-muted-border-color); margin-right: .35rem; vertical-align: middle; }
  .badge { display: inline-block; padding: .15rem .5rem; border-radius: 999px; font-size: .65rem; font-weight: 650; background: var(--hlh-tint); color: var(--pico-primary); }
  .badge.manual { background: var(--pico-primary-background); color: var(--pico-primary-inverse); }
  .chip-list { display: flex; flex-wrap: wrap; gap: .4rem; padding: 0; margin: .6rem 0 0; list-style: none; }
  .chip-list li { font-size: .72rem; padding: .2rem .55rem; border-radius: 999px; background: var(--hlh-tint); color: var(--pico-primary); }
  .sync-controls { display: flex; flex-wrap: wrap; gap: .6rem; align-items: end; }
  .sync-controls label { margin: 0; font-size: .72rem; }
  .sync-controls button { margin: 0; }
  .sync-report { margin-top: 1rem; font-size: .78rem; }
  .change-table pre { white-space: pre-wrap; overflow-wrap: anywhere; max-width: 28rem; margin: 0; padding: .3rem; color: var(--hlh-control-fg); }
  .sync-report details p { overflow-wrap: anywhere; }
  .sync-report ul { margin: .4rem 0; }
  .sync-report p { margin: .3rem 0; }
  @media (max-width: 700px) {
    .groups-page h1 { font-size: 1.5rem; }
    .section-heading { flex-direction: column; align-items: flex-start; gap: .2rem; }
  }
</style>
