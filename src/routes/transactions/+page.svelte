<script lang="ts">
	import { sidecarCall } from '#lib';
	import { goto } from '$app/navigation';

	let ledger = $state<Record<string, unknown> | null>(null);
	let loaded = $state(false);

	async function refresh() {
		ledger = await sidecarCall('wallet_ledger');
	}

	$effect(() => {
		if (loaded) return;
		loaded = true;
		refresh();
	});

	function txs(): Record<string, unknown>[] {
		const raw = ledger?.transactions;
		return Array.isArray(raw) ? (raw as Record<string, unknown>[]) : [];
	}
</script>

<h1>Transactions</h1>
<p class="lead">BZT activity for this wallet from Chain history (Ask/Knowledge settlements included).</p>

<div class="card">
	<button class="ghost" onclick={refresh}>Refresh</button>
	{#if ledger?.has_wallet === false}
		<p class="meta">Create a wallet first.</p>
		<button class="primary" onclick={() => goto('/wallet')}>Wallet</button>
	{:else}
		<p class="mono">{String(ledger?.address || '')}</p>
		<p class="lead">{ledger?.balance ?? '—'} BZT</p>
		{#if ledger?.ok === false}
			<p class="meta" style="color: var(--danger)">{String(ledger.error)}</p>
		{/if}
	{/if}
</div>

<div class="card" style="margin-top:1rem; max-width:none">
	<strong>History</strong>
	{#if txs().length === 0}
		<p class="meta">No transactions indexed for this address yet.</p>
	{/if}
	<ul class="node-list">
		{#each txs() as tx}
			<li>
				<strong>{String(tx.type || tx.tx_type || 'tx')}</strong>
				<span class="caps">
					{String(tx.tx_hash || tx.hash || '').slice(0, 16)}
					{#if tx.amount != null} · {tx.amount} BZT{/if}
					{#if tx.cost != null} · {tx.cost} BZT{/if}
					{#if tx.total_cost != null} · {tx.total_cost} BZT{/if}
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
	}
	.node-list li {
		padding: 0.45rem 0;
		border-bottom: 1px solid var(--border);
	}
</style>
