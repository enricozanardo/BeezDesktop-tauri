<script lang="ts">
	import { sidecarCall } from '#lib';

	let info = $state<Record<string, unknown> | null>(null);
	let blocks = $state<Record<string, unknown>[]>([]);
	let error = $state('');
	let loaded = $state(false);

	async function refresh() {
		error = '';
		const i = await sidecarCall('blockchain_info');
		if (i.ok === false) error = String(i.error);
		info = (i.data as Record<string, unknown>) || i;
		const b = await sidecarCall('recent_blocks');
		const payload = (b.data as Record<string, unknown>) || {};
		const list =
			(payload.blocks as Record<string, unknown>[]) ||
			(payload.items as Record<string, unknown>[]) ||
			[];
		blocks = Array.isArray(list) ? list : [];
		if (b.ok === false && !error) error = String(b.error);
	}

	$effect(() => {
		if (loaded) return;
		loaded = true;
		refresh();
	});

	function chain(): Record<string, unknown> {
		return (info?.blockchain as Record<string, unknown>) || {};
	}
</script>

<h1>Blockchain</h1>
<p class="lead">Live chain height, mempool, and recent blocks from public Chain HTTP nodes.</p>

<div class="card">
	<button class="ghost" onclick={refresh}>Refresh</button>
	{#if error}<p class="meta" style="color: var(--danger)">{error}</p>{/if}
	<p class="mono">Height {String(chain().current_block ?? '—')}</p>
	<p class="meta">
		Mempool {String(chain().mempool_size ?? '—')} · wallets {String(chain().total_wallets ?? '—')}
	</p>
	<p class="meta">Tip {String(chain().last_block_hash_full || chain().last_block_hash || '')}</p>
</div>

<div class="card" style="margin-top:1rem; max-width:none">
	<strong>Recent blocks</strong>
	{#if blocks.length === 0}
		<p class="meta">No blocks returned yet.</p>
	{/if}
	<ul class="node-list">
		{#each blocks as blk}
			<li>
				<strong>#{String(blk.height ?? blk.block_height ?? blk.index ?? '?')}</strong>
				<span class="caps">
					{String(blk.hash || blk.block_hash || '').slice(0, 16)}
					· {Array.isArray(blk.transactions) ? blk.transactions.length : blk.tx_count ?? '?'} txs
				</span>
			</li>
		{/each}
	</ul>
</div>

<style>
	.mono {
		font-family: ui-monospace, monospace;
	}
	.node-list {
		list-style: none;
		padding: 0;
	}
	.node-list li {
		padding: 0.45rem 0;
		border-bottom: 1px solid var(--border);
	}
</style>
