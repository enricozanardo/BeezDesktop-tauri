<script lang="ts">
	import { sidecarCall } from '#lib';
	let ping = $state<Record<string, unknown> | null>(null);

	async function runPing() {
		ping = await sidecarCall('ping');
	}
</script>

<h1>Dashboard</h1>
<p class="lead">Beez Desktop Two — Tokenized Intelligence client (SvelteKit + Tauri). Toga Beez Desktop remains the BeeWare build.</p>
<div class="card">
	<p>Python <code>client_core</code> is invoked through the sidecar (wallet, AES-256-GCM, ECDH, ZMQ).</p>
	<button class="primary" onclick={runPing}>Ping sidecar</button>
	{#if ping}
		<pre>{JSON.stringify(ping, null, 2)}</pre>
	{/if}
</div>
