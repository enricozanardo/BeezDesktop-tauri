<script lang="ts">
	import { sidecarCall } from '#lib';
	let cfg = $state('');
	let ping = $state<Record<string, unknown> | null>(null);

	async function load() {
		const result = await sidecarCall('read_beez_config');
		cfg = result.exists ? String(result.text) : '(no ~/.beez yet)';
		ping = await sidecarCall('ping');
	}
</script>

<h1>Settings</h1>
<p class="lead">
	Network endpoints come from <code>~/.beez</code>. Beez Desktop Two is standalone — install Python
	deps once with <code>pip install -r sidecar/requirements.txt</code> if Ask/Knowledge report missing client_core.
</p>
<div class="card">
	<button class="primary" onclick={load}>Load config & sidecar status</button>
	{#if ping}
		<pre>{JSON.stringify(ping, null, 2)}</pre>
	{/if}
	<pre>{cfg}</pre>
</div>
