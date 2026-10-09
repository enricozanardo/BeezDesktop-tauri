<script lang="ts">
	import { sidecarCall, settings, saveSettings, NOTE_KINDS, testDesktopNotification, refreshLive, appVersion } from '#lib';

	const INTERVALS = [10, 20, 30, 60, 120];

	let version = $state('');
	let ping = $state<Record<string, unknown> | null>(null);
	let cfg = $state('');
	let testResult = $state('');
	let resetMsg = $state('');

	$effect(() => {
		appVersion().then((v) => (version = v));
		sidecarCall('ping').then((p) => (ping = p));
		sidecarCall('read_beez_config').then((r) => (cfg = r.exists ? String(r.text) : ''));
	});

	async function test() {
		testResult = (await testDesktopNotification())
			? 'Sent — check your desktop.'
			: 'Your system did not allow notifications. Enable them for Beez Desktop in the OS settings.';
	}

	async function resetHistory() {
		if (!confirm('Rebuild your transaction history from the chain? This takes a few seconds and changes nothing on chain.')) return;
		const r = await sidecarCall('history_reset');
		resetMsg = r.ok ? 'History cleared; it is being rebuilt in the background.' : String(r.error);
		if (r.ok) refreshLive();
	}
</script>

<h1>Settings</h1>
<p class="lead">How often the app checks the network and what it tells you about.</p>

<div class="split">
	<div class="card stack">
		<h2>Live updates</h2>
		<p class="meta">
			Balances, transactions, file transfers and the explorer update by themselves. A shorter interval
			shows changes sooner; new blocks arrive about every 5 minutes.
		</p>
		<label class="field">
			<span>Check the network every</span>
			<select bind:value={settings.refreshSecs} onchange={saveSettings}>
				{#each INTERVALS as s}<option value={s}>{s < 60 ? `${s} seconds` : `${s / 60} minute${s > 60 ? 's' : ''}`}</option>{/each}
			</select>
		</label>
		<h2 style="margin-top:0.75rem">Transaction history</h2>
		<p class="meta">Your history is cached on this computer and synced incrementally. Rebuild it if it looks incomplete.</p>
		<button class="ghost" onclick={resetHistory}>Rebuild history</button>
		{#if resetMsg}<p class="meta">{resetMsg}</p>{/if}
	</div>

	<div class="card stack">
		<h2>Notifications</h2>
		<label class="switch">
			<input type="checkbox" bind:checked={settings.desktop} onchange={saveSettings} />
			Also show desktop (system) notifications
		</label>
		<button class="ghost" disabled={!settings.desktop} onclick={test}>Send a test notification</button>
		{#if testResult}<p class="meta">{testResult}</p>{/if}
		<p class="meta" style="margin-bottom:0">Notify me about:</p>
		{#each NOTE_KINDS as k (k.kind)}
			<label class="switch">
				<input type="checkbox" bind:checked={settings.kinds[k.kind]} onchange={saveSettings} />
				{k.label}
			</label>
		{/each}
	</div>
</div>

<div class="card stack" style="margin-top:1rem">
	<h2>Connection</h2>
	<dl class="kv">
		<dt>App version</dt><dd>{version || '—'}</dd>
		<dt>Native core</dt><dd>{ping?.ok ? 'running' : ping ? String(ping.error || 'not responding') : '…'}</dd>
		<dt>Network endpoints</dt><dd>{cfg ? 'from ~/.beez (below)' : 'built-in public test-net'}</dd>
	</dl>
	{#if cfg}<pre>{cfg}</pre>{/if}
</div>
