<script lang="ts">
	import { goto } from '$app/navigation';
	import { untrack } from 'svelte';
	import { sidecarCall, live, onLiveTick, refreshLive, txLabel, shortAddr, Pager } from '#lib';

	type Tx = Record<string, unknown>;

	const NETWORK_FEE = 0.01;
	const MAX_MEMO = 280;
	const PAGE = 20;

	let tab = $state<'activity' | 'send'>('activity');
	let kind = $state<'all' | 'sent' | 'received' | 'messages'>('all');
	let query = $state('');
	let offset = $state(0);
	let page = $state<{ total: number; items: Tx[]; syncing: boolean; synced: unknown; error: unknown }>({
		total: 0,
		items: [],
		syncing: false,
		synced: null,
		error: null
	});

	let to = $state('');
	let amount = $state<number | null>(null);
	let memo = $state('');
	let sending = $state(false);
	let sendMsg = $state('');
	let sendErr = $state('');

	const ledger = $derived(live.ledger);
	const pending = $derived(Array.isArray(ledger?.pending) ? (ledger.pending as Tx[]) : []);
	const balance = $derived(Number(ledger?.balance ?? NaN));
	const sendTotal = $derived((Number(amount) || 0) + NETWORK_FEE);
	const toValid = $derived(/^bez[1-9A-HJ-NP-Za-km-z]{20,}$/.test(to.trim()));
	const canSend = $derived(
		toValid && to.trim() !== ledger?.address && memo.length <= MAX_MEMO && ((Number(amount) || 0) > 0 || memo.trim().length > 0) && (Number(amount) || 0) >= 0
	);

	async function load() {
		const r = await sidecarCall('wallet_history', { kind, query, offset, limit: PAGE });
		if (r.ok === false) {
			page = { ...page, error: r.error };
			return;
		}
		page = {
			total: Number(r.total || 0),
			items: (r.transactions as Tx[]) || [],
			syncing: Boolean(r.syncing),
			synced: r.synced_height,
			error: r.sync_error
		};
	}

	$effect(() => {
		untrack(load);
		return onLiveTick(load);
	});

	let searchTimer: ReturnType<typeof setTimeout>;
	function filterChanged() {
		offset = 0;
		clearTimeout(searchTimer);
		searchTimer = setTimeout(load, 250);
	}

	function amountText(tx: Tx): string {
		const n = Number(tx.amount_numeric ?? NaN);
		if (!Number.isFinite(n) || n === 0) return '';
		const sign = tx.direction === 'received' ? '+' : tx.direction === 'sent' ? '−' : '';
		return `${sign}${n} BZT`;
	}

	function pendingAmount(tx: Tx): string {
		const v = tx.cost ?? tx.total_cost ?? tx.purchase_price ?? tx.amount;
		return v == null ? '' : String(v).includes('BZT') ? String(v) : `${v} BZT`;
	}

	function when(tx: Tx): string {
		const t = tx.timestamp;
		return typeof t === 'string' ? t.replace(/ UTC.*/, '') : '';
	}

	async function send() {
		if (!canSend) return;
		const a = Number(amount) || 0;
		const what = [a > 0 ? `${a} BZT` : '', memo.trim() ? `the message “${memo.trim()}”` : ''].filter(Boolean).join(' and ');
		if (!confirm(`Send ${what} to ${to.trim()}?\n\nNetwork fee: ${NETWORK_FEE} BZT. Total debited: ${sendTotal.toFixed(2)} BZT.\nMessages are stored on the public chain.`)) return;
		sending = true;
		sendErr = sendMsg = '';
		const r = await sidecarCall('send_transfer', { recipient: to.trim(), amount: a, memo: memo.trim() });
		sending = false;
		if (r.ok) {
			sendMsg = `Sent. It appears under Pending now and in Activity after the next block. Transaction ${String(r.tx_hash).slice(0, 16)}…`;
			amount = null;
			memo = '';
			refreshLive();
		} else {
			sendErr = String(r.error);
		}
	}

	function replyTo(tx: Tx) {
		to = String(tx.counterparty || '');
		tab = 'send';
	}
</script>

<h1>Transactions</h1>
<p class="lead">
	Your BZT activity, kept in a local cache that updates by itself. Send BZT or a short text message to any
	wallet.
</p>

{#if ledger?.has_wallet === false}
	<div class="card row" style="justify-content:space-between">
		<p class="meta">Create a wallet first.</p>
		<button class="primary" onclick={() => goto('/wallet')}>Wallet</button>
	</div>
{:else}
	<div class="stats">
		<div class="stat">
			<div class="value">{Number.isFinite(balance) ? balance.toLocaleString(undefined, { maximumFractionDigits: 6 }) : '—'}</div>
			<div class="label">Balance (BZT)</div>
		</div>
		<div class="stat">
			<div class="value">{pending.length}</div>
			<div class="label">Waiting for a block</div>
		</div>
		<div class="stat">
			<div class="value">{page.total}</div>
			<div class="label">{kind === 'all' && !query ? 'Confirmed transactions' : 'Matching transactions'}</div>
		</div>
	</div>
	<p class="meta mono">{String(ledger?.address || '')}</p>
	{#if ledger?.ok === false}<p class="error">{String(ledger.error)}</p>{/if}

	<div class="tabs">
		<button class:active={tab === 'activity'} onclick={() => (tab = 'activity')}>Activity</button>
		<button class:active={tab === 'send'} onclick={() => (tab = 'send')}>Send BZT or message</button>
	</div>

	{#if tab === 'send'}
		<div class="split">
			<div class="card stack">
				<label class="field">
					<span>Recipient wallet</span>
					<input type="text" bind:value={to} placeholder="bez…" spellcheck="false" />
					{#if to && !toValid}<span class="error">Not a valid bez… address.</span>{/if}
					{#if to.trim() === ledger?.address}<span class="error">That is your own wallet.</span>{/if}
				</label>
				<label class="field">
					<span>Amount (BZT) — leave empty to send only a message</span>
					<input type="number" min="0" step="0.000001" bind:value={amount} placeholder="0" />
				</label>
				<label class="field">
					<span>Message (optional, {memo.length}/{MAX_MEMO})</span>
					<textarea bind:value={memo} maxlength={MAX_MEMO} placeholder="e.g. Payment for invoice 42"></textarea>
				</label>
				<button class="primary" disabled={!canSend || sending} onclick={send}>{sending ? 'Sending…' : 'Review and send'}</button>
				{#if sendMsg}<p class="callout">{sendMsg}</p>{/if}
				{#if sendErr}<p class="error">{sendErr}</p>{/if}
			</div>
			<div class="card stack">
				<h3>Summary</h3>
				<dl class="kv">
					<dt>Amount</dt>
					<dd>{(Number(amount) || 0).toFixed(6)} BZT</dd>
					<dt>Network fee</dt>
					<dd>{NETWORK_FEE.toFixed(2)} BZT</dd>
					<dt>Total debited</dt>
					<dd class="total">{sendTotal.toFixed(6)} BZT</dd>
					<dt>Balance after</dt>
					<dd>{Number.isFinite(balance) ? (balance - sendTotal).toFixed(6) : '—'} BZT</dd>
				</dl>
				<p class="callout">
					Messages travel inside a signed transaction: the recipient sees them in Activity and gets a
					notification. They are public on the chain, so do not send secrets.
				</p>
			</div>
		</div>
	{:else}
		{#if pending.length}
			<div class="card" style="margin-bottom:1rem">
				<h2>Waiting for a block ({pending.length})</h2>
				<ul class="list">
					{#each pending as tx (tx.tx_hash)}
						<li>
							<span class="chip warn">pending</span>
							<strong>{txLabel(tx)}</strong>
							<span class="sub">{pendingAmount(tx)} · {String(tx.tx_hash || '').slice(0, 16)}…</span>
							{#if tx.memo}<span class="memo">{String(tx.memo)}</span>{/if}
						</li>
					{/each}
				</ul>
			</div>
		{/if}

		<div class="card">
			<div class="toolbar">
				<label class="field">
					<span>Show</span>
					<select bind:value={kind} onchange={filterChanged}>
						<option value="all">Everything</option>
						<option value="received">Received</option>
						<option value="sent">Sent</option>
						<option value="messages">Messages</option>
					</select>
				</label>
				<label class="field grow">
					<span>Search (address, message, file name, type, hash)</span>
					<input type="search" bind:value={query} oninput={filterChanged} placeholder="Search…" />
				</label>
			</div>
			{#if page.syncing && page.synced == null}
				<p class="meta">Building your local history from the chain for the first time — this takes a few seconds…</p>
			{:else if page.error}
				<p class="error">Could not update history: {String(page.error)}</p>
			{/if}
			{#if page.items.length === 0 && !(page.syncing && page.synced == null)}
				<p class="meta">{kind === 'all' && !query ? 'No confirmed transactions for this wallet yet.' : 'Nothing matches these filters.'}</p>
			{/if}
			<ul class="list">
				{#each page.items as tx (tx.tx_hash)}
					<li>
						<span class="chip {tx.direction === 'received' ? 'ok' : 'muted'}">{String(tx.direction || '')}</span>
						<strong>{txLabel(tx)}</strong>
						<span>{amountText(tx)}</span>
						<span class="sub">
							{#if tx.counterparty}{tx.direction === 'received' ? 'from' : 'to'} {shortAddr(tx.counterparty)} ·{/if}
							{#if tx.file_name}{String(tx.file_name)} ·{/if}
							{when(tx)} · <a href={`/blockchain?block=${tx.block_height}`}>block {String(tx.block_height ?? '—')}</a>
						</span>
						{#if tx.memo}
							<span class="memo">{String(tx.memo)}</span>
						{/if}
						{#if (tx.type === 'normal' || tx.type === 'transfer') && tx.direction === 'received'}
							<button class="ghost" onclick={() => replyTo(tx)}>Reply</button>
						{/if}
					</li>
				{/each}
			</ul>
			<Pager total={page.total} limit={PAGE} bind:offset onchange={load} />
			<p class="meta">Synced up to block {String(page.synced ?? '—')}{page.syncing ? ' · updating…' : ''}</p>
		</div>
	{/if}
{/if}
