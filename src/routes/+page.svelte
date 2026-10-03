<script lang="ts">
	import { sidecarCall } from '#lib';
	let ping = $state<Record<string, unknown> | null>(null);

	async function runPing() {
		ping = await sidecarCall('ping');
	}
</script>

<h1>Dashboard</h1>
<p class="lead">Network overview. Toga BeezDesktop remains the production client until this shell has feature parity.</p>
<div class="card">
	<p>Python <code>client_core</code> is invoked through the sidecar (wallet, AES-256-GCM, ECDH, ZMQ).</p>
	<button class="primary" onclick={runPing}>Ping sidecar</button>
	{#if ping}
		<pre>{JSON.stringify(ping, null, 2)}</pre>
	{/if}
</div>
