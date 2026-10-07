<script lang="ts">
	import { sidecarCall } from '#lib';
	import { goto } from '$app/navigation';

	type Tx = Record<string, unknown>;

	const TYPE_LABELS: Record<string, string> = {
		smart_query: 'Ask question',
		smart_index: 'Ask indexing',
		knowledge_publish: 'Knowledge listing published',
		knowledge_query: 'Knowledge question',
		knowledge_purchase: 'Knowledge purchase',
		upload: 'File upload',
		transfer: 'Transfer',
		reward: 'Reward'
	};

	let ledger = $state<Record<string, unknown> | null>(null);
	let loaded = $state(false);

	const history = $derived(Array.isArray(ledger?.transactions) ? (ledger.transactions as Tx[]) : []);
	const pending = $derived(Array.isArray(ledger?.pending) ? (ledger.pending as Tx[]) : []);

	async function refresh() {
		ledger = await sidecarCall('wallet_ledger');
	}

	$effect(() => {
		if (loaded) return;
		loaded = true;
		refresh();
	});

	function label(tx: Tx): string {
		const t = String(tx.type || tx.tx_type || 'tx');
		return TYPE_LABELS[t] || t;
	}

	function pendingAmount(tx: Tx): string {
		const v = tx.cost ?? tx.total_cost ?? tx.purchase_price ?? tx.amount;
		return v == null ? '' : String(v).includes('BZT') ? String(v) : `${v} BZT`;
	}
</script>

<h1>Transactions</h1>
<p class="lead">
	BZT activity for this wallet. New payments (Ask, Knowledge, uploads) appear under Pending immediately
	and move to History once a block confirms them (~5 min).
</p>

<div class="card row" style="justify-content:space-between">
	{#if ledger?.has_wallet === false}
		<p class="meta">Create a wallet first.</p>
		<button class="primary" onclick={() => goto('/wallet')}>Wallet</button>
	{:else}
		<div>
			<p class="mono" style="margin:0">{String(ledger?.address || '')}</p>
			<p class="lead" style="margin:0.25rem 0 0">Balance <strong>{ledger?.balance ?? '—'} BZT</strong></p>
			{#if ledger?.ok === false}
				<p class="meta" style="color: var(--danger)">{String(ledger.error)}</p>
			{/if}
		</div>
		<button class="ghost" onclick={refresh}>Refresh</button>
	{/if}
</div>

<div class="card" style="margin-top:1rem">
	<h2>Pending ({pending.length})</h2>
	{#if pending.length === 0}
		<p class="meta">Nothing waiting for confirmation.</p>
	{/if}
	<ul class="node-list">
		{#each pending as tx}
			<li>
				<span class="chip warn">pending</span>
				<strong>{label(tx)}</strong>
				<span class="caps">{pendingAmount(tx)} · {String(tx.tx_hash || '').slice(0, 16)}</span>
			</li>
		{/each}
	</ul>
</div>

<div class="card" style="margin-top:1rem">
	<h2>History</h2>
	{#if history.length === 0}
		<p class="meta">No confirmed transactions for this address yet.</p>
	{/if}
	<ul class="node-list">
		{#each history as tx}
			<li>
				<span class="chip {tx.direction === 'received' ? 'ok' : 'muted'}">{String(tx.direction || '')}</span>
				<strong>{label(tx)}</strong>
				<span class="caps">
					{String(tx.amount ?? '')}
					· block {String(tx.block_height ?? '—')}
					· {String(tx.tx_hash || '').slice(0, 16)}
				</span>
			</li>
		{/each}
	</ul>
</div>

<style>
	.mono {
		font-family: ui-monospace, monospace;
		word-break: break-all;
	}
	.node-list {
		list-style: none;
		padding: 0;
		margin: 0;
	}
	.node-list li {
		padding: 0.6rem 0;
		border-bottom: 1px solid var(--border);
		display: flex;
		gap: 0.75rem;
		align-items: center;
		flex-wrap: wrap;
	}
	.caps {
		color: var(--muted);
		font-size: 0.88rem;
	}
</style>
