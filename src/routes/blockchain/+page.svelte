<script lang="ts">
	import { page } from '$app/state';
	import { goto } from '$app/navigation';
	import { untrack } from 'svelte';
	import { sidecarCall, onLiveTick, txLabel, shortAddr, Pager } from '#lib';

	type Rec = Record<string, unknown>;

	const PAGE = 20;
	const HIDDEN_FIELDS = new Set(['sig', 'pub', 'signature', 'memo_private', 'memo_error']);
	const PARTY_FIELDS = [
		'sender', 'recipient', 'uploader', 'wallet_address', 'smart_node_wallet', 'buyer_address',
		'seller_address', 'current_owner', 'new_owner', 'owner_address', 'dam_address', 'target_node_address'
	];

	let info = $state<Rec>({});
	let blocks = $state<Rec[]>([]);
	let total = $state(0);
	let offset = $state(0);
	let query = $state('');
	let error = $state('');
	let busy = $state(false);

	let block = $state<Rec | null>(null);
	let tx = $state<Rec | null>(null);
	let txStatus = $state('');
	let wallet = $state<Rec | null>(null);
	let typeFilter = $state('');

	const params = $derived(page.url.searchParams);
	const view = $derived(params.get('block') ? 'block' : params.get('tx') ? 'tx' : params.get('wallet') ? 'wallet' : 'list');
	const height = $derived(Number(info.current_block ?? NaN));

	async function loadInfo() {
		const i = await sidecarCall('blockchain_info');
		info = ((i.data as Rec)?.blockchain as Rec) || {};
		if (i.ok === false) error = String(i.error);
	}

	async function loadList() {
		const b = await sidecarCall('blocks_page', { limit: PAGE, offset });
		const d = (b.data as Rec) || {};
		blocks = (d.blocks as Rec[]) || [];
		total = Number(d.total || 0);
		if (b.ok === false) error = String(b.error);
	}

	async function loadView() {
		error = '';
		if (view === 'block') {
			busy = true;
			const r = await sidecarCall('block_detail', { height: Number(params.get('block')) });
			busy = false;
			block = r.ok ? ((r.data as Rec).block as Rec) : null;
			if (!r.ok) error = String(r.error);
		} else if (view === 'tx') {
			busy = true;
			const r = await sidecarCall('transaction_detail', { hash: params.get('tx') });
			busy = false;
			tx = r.ok ? (r.transaction as Rec) : null;
			txStatus = String(r.status || '');
			if (!r.ok) error = String(r.error);
		} else if (view === 'wallet') {
			busy = true;
			wallet = null;
			const r = await sidecarCall('explorer_wallet', { address: params.get('wallet'), limit: 50 });
			busy = false;
			wallet = r.ok ? (r.data as Rec) : null;
			if (!r.ok) error = String(r.error);
		}
	}

	$effect(() => {
		loadInfo();
		return onLiveTick(async () => {
			await loadInfo();
			if (view === 'list') await loadList();
		});
	});

	$effect(() => {
		void params.toString();
		const v = view;
		untrack(() => {
			typeFilter = '';
			if (v === 'list') loadList();
			else loadView();
		});
	});

	async function search() {
		error = '';
		busy = true;
		const r = await sidecarCall('explorer_search', { query });
		busy = false;
		if (!r.ok) {
			error = String(r.error);
			return;
		}
		if (r.kind === 'block') goto(`/blockchain?block=${r.height}`);
		else if (r.kind === 'transaction') goto(`/blockchain?tx=${r.hash}`);
		else goto(`/blockchain?wallet=${r.address}`);
	}

	function ts(v: unknown): string {
		const raw = typeof v === 'object' && v ? (v as Rec).timestamp : v;
		return typeof raw === 'string' ? raw.replace(/ UTC.*/, '') : raw ? String(raw) : '—';
	}

	function parties(t: Rec): string {
		const seen = PARTY_FIELDS.map((k) => t[k]).filter((v): v is string => typeof v === 'string' && v.startsWith('bez'));
		return [...new Set(seen)].map(shortAddr).join(' → ');
	}

	function value(t: Rec): string {
		const v = t.amount ?? t.total_cost ?? t.cost ?? t.asking_price ?? t.purchase_price ?? t.storage_cost_BZT;
		if (v == null || v === '') return '';
		return String(v).includes('BZT') ? String(v) : `${v} BZT`;
	}

	function fieldText(v: unknown): string {
		if (v == null) return '—';
		if (typeof v === 'string') return v.length > 300 ? `${v.slice(0, 300)}… (${v.length} characters)` : v;
		return JSON.stringify(v, null, 1);
	}

	const blockTxs = $derived(((block?.body as Rec)?.txs as Rec[]) || []);
	const blockTypes = $derived([...new Set(blockTxs.map((t) => String(t.type || 'normal')))].sort());
	const shownTxs = $derived(typeFilter ? blockTxs.filter((t) => String(t.type || 'normal') === typeFilter) : blockTxs);
	const blockHeight = $derived(Number((block?.header as Rec)?.height ?? params.get('block')));
</script>

<h1>Blockchain</h1>
<p class="lead">Explore blocks and transactions on the public chain. Updates by itself as new blocks arrive.</p>

<div class="stats">
	<div class="stat"><div class="value">{Number.isFinite(height) ? height.toLocaleString() : '—'}</div><div class="label">Latest block</div></div>
	<div class="stat"><div class="value">{String(info.mempool_size ?? '—')}</div><div class="label">Transactions waiting</div></div>
	<div class="stat"><div class="value">{info.total_wallets != null ? Number(info.total_wallets).toLocaleString() : '—'}</div><div class="label">Wallets</div></div>
</div>

<form class="toolbar" style="margin-top:1rem" onsubmit={(e) => { e.preventDefault(); search(); }}>
	<label class="field grow">
		<span>Find a block height, block or transaction hash, or a bez… wallet</span>
		<input type="search" bind:value={query} placeholder="e.g. 152390, 3f9a…, bez…" spellcheck="false" />
	</label>
	<button class="primary" disabled={!query.trim() || busy}>Search</button>
	{#if view !== 'list'}<button type="button" class="ghost" onclick={() => goto('/blockchain')}>All blocks</button>{/if}
</form>
{#if error}<p class="error">{error}</p>{/if}

{#if view === 'list'}
	<div class="card">
		<h2>Latest blocks</h2>
		<ul class="list">
			{#each blocks as b (b.height)}
				<li>
					<button class="rowlink" onclick={() => goto(`/blockchain?block=${b.height}`)}>
						<strong>#{Number(b.height).toLocaleString()}</strong>
						<span class="chip muted">{String(b.tx_count)} transactions</span>
						<span class="sub">{ts(b.timestamp)} · mined by {shortAddr(b.miner)} · {String(b.hash || '').slice(0, 16)}…</span>
					</button>
				</li>
			{/each}
		</ul>
		<Pager {total} limit={PAGE} bind:offset onchange={loadList} />
	</div>
{:else if view === 'block'}
	<div class="card stack">
		<div class="row" style="justify-content:space-between">
			<h2 style="margin:0">Block #{Number.isFinite(blockHeight) ? blockHeight.toLocaleString() : '…'}</h2>
			<div class="row">
				<button class="ghost" disabled={!(blockHeight > 0) || busy} onclick={() => goto(`/blockchain?block=${blockHeight - 1}`)}>← Previous</button>
				<button class="ghost" disabled={!(blockHeight < height) || busy} onclick={() => goto(`/blockchain?block=${blockHeight + 1}`)}>Next →</button>
			</div>
		</div>
		{#if busy && !block}<p class="meta">Loading…</p>{/if}
		{#if block}
			<dl class="kv">
				<dt>Hash</dt><dd class="mono">{String((block.header as Rec)?.hash)}</dd>
				<dt>Previous</dt><dd class="mono">{String((block.header as Rec)?.prev_hash)}</dd>
				<dt>Time</dt><dd>{ts((block.node as Rec)?.timestamp)}</dd>
				<dt>Mined by</dt><dd class="mono"><a href={`/blockchain?wallet=${(block.node as Rec)?.miner_address}`}>{String((block.node as Rec)?.miner_address)}</a></dd>
				<dt>Transactions</dt><dd>{blockTxs.length}</dd>
			</dl>
			<div class="toolbar">
				<label class="field">
					<span>Transaction type</span>
					<select bind:value={typeFilter}>
						<option value="">All ({blockTxs.length})</option>
						{#each blockTypes as t}<option value={t}>{txLabel({ type: t })} ({blockTxs.filter((x) => String(x.type || 'normal') === t).length})</option>{/each}
					</select>
				</label>
			</div>
			<ul class="list">
				{#each shownTxs as t, i (String(t.tx_hash || i))}
					<li>
						<button class="rowlink" disabled={!t.tx_hash} onclick={() => goto(`/blockchain?tx=${t.tx_hash}`)}>
							<strong>{txLabel(t)}</strong>
							<span>{value(t)}</span>
							<span class="sub">{parties(t)} · {String(t.tx_hash || '').slice(0, 16)}…</span>
						</button>
						{#if t.memo_enc}<span class="chip muted">Encrypted message</span>{:else if t.memo}<span class="memo">{String(t.memo)}</span>{/if}
					</li>
				{/each}
			</ul>
		{/if}
	</div>
{:else if view === 'tx'}
	<div class="card stack">
		<div class="row" style="justify-content:space-between">
			<h2 style="margin:0">{tx ? txLabel(tx) : 'Transaction'}</h2>
			{#if txStatus === 'pending'}<span class="chip warn">waiting for a block</span>{:else if tx}<span class="chip ok">confirmed</span>{/if}
		</div>
		{#if busy && !tx}<p class="meta">Loading…</p>{/if}
		{#if tx}
			{#if tx.block_height != null}
				<p><button class="ghost" onclick={() => goto(`/blockchain?block=${tx?.block_height}`)}>Open block #{Number(tx.block_height).toLocaleString()}</button></p>
			{/if}
			{#if tx.memo_private}
				<p class="memo">{String(tx.memo)}</p>
				<p class="meta">Message decrypted on this device. On chain it is stored encrypted; only the sender and the recipient can read it.</p>
			{:else if tx.memo_enc}
				<p class="meta">Encrypted message: only the sender and the recipient can read it.{#if tx.memo_error} ({String(tx.memo_error)}){/if}</p>
			{:else if tx.memo}
				<p class="memo">{String(tx.memo)}</p>
			{/if}
			<dl class="kv">
				{#each Object.entries(tx).filter(([k]) => !HIDDEN_FIELDS.has(k) && !(tx?.memo_private && k === 'memo')) as [k, v] (k)}
					<dt>{k.replaceAll('_', ' ')}</dt>
					<dd class:mono={typeof v === 'string'}>
						{#if typeof v === 'string' && v.startsWith('bez')}<a href={`/blockchain?wallet=${v}`}>{v}</a>{:else}{fieldText(v)}{/if}
					</dd>
				{/each}
			</dl>
		{/if}
	</div>
{:else if view === 'wallet'}
	<div class="card stack">
		<h2 style="margin:0">Wallet</h2>
		<p class="mono">{params.get('wallet')}</p>
		{#if busy}<p class="meta">Scanning the chain for this wallet's transactions — this can take up to a minute…</p>{/if}
		{#if wallet}
			<dl class="kv">
				<dt>Balance</dt><dd>{String(wallet.balance ?? '—')} BZT</dd>
				<dt>Received</dt><dd>{String(wallet.total_received ?? '—')} BZT</dd>
				<dt>Sent</dt><dd>{String(wallet.total_sent ?? '—')} BZT</dd>
			</dl>
			<h3>Latest {((wallet.transactions as Rec[]) || []).length} transactions</h3>
			<ul class="list">
				{#each (wallet.transactions as Rec[]) || [] as t (t.tx_hash)}
					<li>
						<button class="rowlink" onclick={() => goto(`/blockchain?tx=${t.tx_hash}`)}>
							<span class="chip {t.direction === 'received' ? 'ok' : 'muted'}">{String(t.direction)}</span>
							<strong>{txLabel(t)}</strong>
							<span>{String(t.amount ?? '')}</span>
							<span class="sub">block {String(t.block_height)} · {String(t.tx_hash).slice(0, 16)}…</span>
						</button>
						{#if t.memo_enc}<span class="chip muted">Encrypted message</span>{:else if t.memo}<span class="memo">{String(t.memo)}</span>{/if}
					</li>
				{/each}
			</ul>
		{/if}
	</div>
{/if}
