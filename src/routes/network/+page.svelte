<script lang="ts">
	import { sidecarCall } from '#lib';

	let nodes = $state<Record<string, unknown>[]>([]);
	let errors = $state<unknown[]>([]);
	let loaded = $state(false);

	async function refresh() {
		const r = await sidecarCall('list_smart_nodes');
		nodes = (r.nodes as Record<string, unknown>[]) || [];
		errors = (r.errors as unknown[]) || [];
	}

	$effect(() => {
		if (loaded) return;
		loaded = true;
		refresh();
	});
</script>

<h1>Network</h1>
<p class="lead">Smart nodes from Directory consensus (plus Local MiniCPM). Full DAM/Storage roster comes later.</p>
<div class="card">
	<button class="ghost" onclick={refresh}>Refresh</button>
	{#if errors.length}
		<pre>{JSON.stringify(errors, null, 2)}</pre>
	{/if}
	<ul class="node-list">
		{#each nodes as n}
			<li>
				<strong>{String(n.label || n.node_id)}</strong>
				<span class="caps">
					{(Array.isArray(n.capabilities) ? n.capabilities.join(', ') : 'generic') as string}
					· {String(n.llm_backend || '')}
					· {n.price_per_query ?? '?'} BZT
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
