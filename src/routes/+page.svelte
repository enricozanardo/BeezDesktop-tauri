<script lang="ts">
	import { sidecarCall } from '#lib';
	import { goto } from '$app/navigation';

	let wallet = $state<Record<string, unknown> | null>(null);
	let ledger = $state<Record<string, unknown> | null>(null);
	let chain = $state<Record<string, unknown> | null>(null);
	let nodes = $state<Record<string, unknown>[]>([]);
	let coreOk = $state<boolean | null>(null);
	let error = $state('');
	let loaded = $state(false);

	async function refresh() {
		error = '';
		const ping = await sidecarCall('ping');
		coreOk = ping.ok !== false && Boolean(ping.client_core);
		if (ping.ok === false) {
			error = String(ping.error || 'native core unavailable');
			return;
		}
		wallet = await sidecarCall('wallet_status');
		ledger = await sidecarCall('wallet_ledger');
		const info = await sidecarCall('blockchain_info');
		chain = (info.data as Record<string, unknown>) || null;
		const listed = await sidecarCall('list_smart_nodes');
		nodes = ((listed.nodes as Record<string, unknown>[]) || []).slice(0, 6);
		if (listed.ok === false && !error) {
			error = String(listed.error || '');
		}
	}

	$effect(() => {
		if (loaded) return;
		loaded = true;
		refresh();
	});
</script>

<h1>Home</h1>
<p class="lead">
	Beez Desktop Two is a standalone Tokenized Intelligence client. Create a wallet, pick a Smart
	node, Ask with citations, or browse Knowledge.
</p>

<div class="home-grid">
	<div class="card">
		<strong>Wallet</strong>
		{#if wallet?.has_wallet}
			<p class="mono">{String(wallet.address)}</p>
			<p class="lead">{ledger?.balance ?? '—'} BZT</p>
			{#if wallet.migrated_from}
				<p class="meta">Migrated from {String(wallet.migrated_from)} storage.</p>
			{/if}
			<button class="ghost" onclick={() => goto('/wallet')}>Manage wallet</button>
		{:else}
			<p class="meta">No wallet yet. Generate or import a 12-word mnemonic to use Ask and Knowledge.</p>
			<button class="primary" onclick={() => goto('/wallet')}>Set up wallet</button>
		{/if}
	</div>

	<div class="card">
		<strong>Core</strong>
		<p class="meta">
			Native engine:
			{#if coreOk === null}…{:else if coreOk}
				<span class="ok">ready</span>
			{:else}
				<span class="bad">unavailable</span>
			{/if}
		</p>
		<p class="meta">
			Height {String((chain?.blockchain as Record<string, unknown> | undefined)?.current_block ?? '—')}
		</p>
		<button class="ghost" onclick={refresh}>Refresh status</button>
	</div>

	<div class="card wide">
		<strong>Smart nodes</strong>
		{#if nodes.length === 0}
			<p class="meta">No Smart nodes discovered yet. Check ~/.beez and network reachability.</p>
		{:else}
			<ul class="node-list">
				{#each nodes as n}
					<li>
						{String(n.label || n.node_id)}
						<span class="caps">
							{(Array.isArray(n.capabilities) ? n.capabilities.join(', ') : 'generic') as string}
							· {n.price_per_query ?? '?'} BZT
						</span>
					</li>
				{/each}
			</ul>
		{/if}
		<div class="row">
			<button class="primary" onclick={() => goto('/smart')}>Open Ask</button>
			<button class="ghost" onclick={() => goto('/knowledge')}>Knowledge</button>
		</div>
	</div>
</div>

{#if error}
	<p class="meta bad">{error}</p>
{/if}

<style>
	.home-grid {
		display: grid;
		grid-template-columns: 1fr 1fr;
		gap: 1rem;
	}
	.card.wide {
		grid-column: 1 / -1;
	}
	.mono {
		font-family: ui-monospace, monospace;
		word-break: break-all;
		font-size: 0.9rem;
	}
	.ok {
		color: #6ecf8e;
	}
	.bad {
		color: var(--danger);
	}
	.node-list {
		list-style: none;
		padding: 0;
		margin: 0.75rem 0;
	}
	.node-list li {
		padding: 0.4rem 0;
		border-bottom: 1px solid var(--border);
	}
	@media (max-width: 800px) {
		.home-grid {
			grid-template-columns: 1fr;
		}
	}
</style>
