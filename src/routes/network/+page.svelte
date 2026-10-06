<script lang="ts">
	import { sidecarCall } from '#lib';

	let nodes = $state<Record<string, unknown>[]>([]);
	let errors = $state<unknown[]>([]);
	let source = $state('');
	let loaded = $state(false);

	async function refresh() {
		const r = await sidecarCall('list_network_nodes');
		nodes = (r.nodes as Record<string, unknown>[]) || [];
		errors = (r.errors as unknown[]) || [];
		source = String(r.source || '');
	}

	$effect(() => {
		if (loaded) return;
		loaded = true;
		refresh();
	});
</script>

<h1>Network</h1>
<p class="lead">Directory roster (all node types) from the live test-net. Source: {source || '—'}</p>
<div class="card" style="max-width:none">
	<button class="ghost" onclick={refresh}>Refresh</button>
	{#if errors.length}
		<pre>{JSON.stringify(errors, null, 2)}</pre>
	{/if}
	<ul class="node-list">
		{#each nodes as n}
			<li>
				<strong>{String(n.node_id || n.ip)}</strong>
				<span class="caps">
					{String(n.node_type || '?')} · {String(n.ip || '')}
					{#if n.capabilities}
						· {(Array.isArray(n.capabilities) ? n.capabilities.join(', ') : String(n.capabilities)) as string}
					{/if}
					{#if n.price_per_query != null} · {n.price_per_query} BZT/query{/if}
				</span>
			</li>
		{/each}
	</ul>
</div>

<style>
	.node-list {
		list-style: none;
		padding: 0;
	}
	.node-list li {
		padding: 0.5rem 0;
		border-bottom: 1px solid var(--border);
	}
</style>
