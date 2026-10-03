<script lang="ts">
	import { sidecarCall } from '#lib';
	let cfg = $state('');

	async function load() {
		const result = await sidecarCall('read_beez_config');
		cfg = result.exists ? String(result.text) : '(no ~/.beez yet)';
	}
</script>

<h1>Settings</h1>
<p class="lead">Network type, directory nodes, ZMQ, log level — same <code>~/.beez</code> file as Toga.</p>
<div class="card">
	<button class="primary" onclick={load}>Load ~/.beez</button>
	<pre>{cfg}</pre>
</div>
