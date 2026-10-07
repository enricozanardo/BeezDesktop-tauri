<script lang="ts">
	import { goto } from '$app/navigation';
	import { sidecarCall, WorkspacePicker } from '#lib';
	import type { WorkspaceFile } from '#lib';

	type SmartNode = Record<string, unknown> & {
		node_id?: string;
		instance_id?: string;
		label?: string;
		llm_model?: string;
		llm_available?: boolean;
		available?: boolean;
	};

	type Listing = {
		listing_id: string;
		title?: string;
		description?: string;
		price_per_query?: number;
		purchase_price?: number;
		seller_address?: string;
		status?: string;
		tags?: string[];
		total_files?: number;
		total_chunks?: number;
		total_queries?: number;
		created_at?: string;
		files?: WorkspaceFile[];
	};

	type ListingStats = {
		listing_id: string;
		queries: number;
		query_revenue: number;
		purchases: number;
		purchase_revenue: number;
		unique_buyers: number;
		total_revenue: number;
	};

	type Totals = {
		queries?: number;
		purchases?: number;
		query_revenue?: number;
		purchase_revenue?: number;
		total_revenue?: number;
	};

	type Tab = 'browse' | 'sell' | 'mine';

	// Mirrors BeezChain fee_config.TRANSACTION_FEES and the 80/20 split in _apply_tx.
	const NETWORK_FEE = { publish: 0.05, query: 0.01, purchase: 0.05 };
	const SELLER_SHARE = 0.8;

	let tab = $state<Tab>('browse');
	let nodes = $state<SmartNode[]>([]);
	let node = $state<SmartNode | null>(null);
	let address = $state('');
	let balance = $state<number | null>(null);
	let busy = $state(false);
	let status = $state('');

	let query = $state('');
	let listings = $state<Listing[]>([]);
	let selected = $state<Listing | null>(null);
	let ask = $state('');
	let answer = $state('');

	let workspaceFiles = $state<WorkspaceFile[]>([]);
	let pubSelected = $state<string[]>([]);
	let pubTitle = $state('');
	let pubDesc = $state('');
	let pubTags = $state('');
	let pubPrice = $state(0.1);
	let pubPurchase = $state(0);

	let mine = $state<Listing[]>([]);
	let stats = $state<ListingStats[]>([]);
	let totals = $state<Totals>({});
	let statsError = $state('');
	let editing = $state<string | null>(null);
	let edit = $state({ title: '', description: '', tags: '', price_per_query: 0, purchase_price: 0 });

	const statsById = $derived(new Map(stats.map((s) => [s.listing_id, s])));
	const offNode = $derived(stats.filter((s) => !mine.some((l) => l.listing_id === s.listing_id)));
	const activeCount = $derived(mine.filter((l) => l.status === 'active').length);

	function bzt(n: number | undefined | null): string {
		const v = Number(n || 0);
		return `${Number.isInteger(v) ? v : v.toFixed(v < 1 ? 4 : 2).replace(/0+$/, '').replace(/\.$/, '')} BZT`;
	}

	function nodeLabel(n: SmartNode | null): string {
		if (!n) return 'No node';
		return String(n.label || n.instance_id || n.node_id || 'Smart');
	}

	function nodeUsable(n: SmartNode | null): boolean {
		return Boolean(n) && n?.llm_available !== false && n?.available !== false;
	}

	function statusChip(s?: string): string {
		if (s === 'active') return 'ok';
		if (s === 'paused') return 'warn';
		return 'muted';
	}

	function parseTags(s: string): string[] {
		return s
			.split(',')
			.map((t) => t.trim())
			.filter(Boolean);
	}

	async function refreshWallet() {
		const ledger = await sidecarCall('wallet_ledger');
		address = String(ledger.address || '');
		const n = Number(ledger.balance);
		balance = ledger.ok !== false && ledger.balance != null && !Number.isNaN(n) ? n : null;
	}

	async function loadNodes() {
		const r = (await sidecarCall('list_smart_nodes')) as Record<string, unknown>;
		nodes = ((r.nodes as SmartNode[]) || []).filter((n) => n.node_id !== 'local_minicpm');
		const current = nodes.find((n) => n.node_id === node?.node_id);
		node = current || nodes.find(nodeUsable) || nodes[0] || null;
	}

	async function loadWorkspace() {
		if (!node) return;
		const r = (await sidecarCall('workspace_stats', { node })) as Record<string, unknown>;
		workspaceFiles = Array.isArray(r.files) ? (r.files as WorkspaceFile[]) : [];
		pubSelected = pubSelected.filter((id) => workspaceFiles.some((f) => f.file_id === id));
	}

	async function search() {
		if (!node) return;
		const r = (await sidecarCall('knowledge_search', { node, query })) as Record<string, unknown>;
		listings = (r.listings as Listing[]) || [];
		if (r.ok === false) status = String(r.error);
		if (selected && !listings.some((l) => l.listing_id === selected?.listing_id)) selected = null;
	}

	async function loadMine() {
		if (!node) return;
		const [m, s] = await Promise.all([
			sidecarCall('knowledge_mine', { node }),
			sidecarCall('knowledge_seller_stats')
		]);
		mine = ((m as Record<string, unknown>).listings as Listing[]) || [];
		statsError = s.ok === false ? String(s.error) : '';
		stats = (s.listings as ListingStats[]) || [];
		totals = (s.totals as Totals) || {};
	}

	async function switchNode(id: string) {
		node = nodes.find((n) => n.node_id === id) || node;
		selected = null;
		answer = '';
		await Promise.all([loadWorkspace(), search(), loadMine()]);
	}

	async function queryListing() {
		if (!node || !selected || !ask.trim() || busy) return;
		const cost = Number(selected.price_per_query || 0);
		await refreshWallet();
		const total = cost + NETWORK_FEE.query;
		if (balance != null && balance < total) {
			status = `Not enough BZT: this question costs ${bzt(total)}, your wallet has ${bzt(balance)}.`;
			return;
		}
		if (
			!confirm(
				`Ask “${selected.title}” for ${bzt(cost)} + ${bzt(NETWORK_FEE.query)} network fee?\n` +
					`You receive an AI answer based on the seller's documents (not the documents themselves).`
			)
		)
			return;
		busy = true;
		answer = '';
		status = 'Preparing the question…';
		const ready = await sidecarCall('embed_ensure');
		if (ready.ok === false) {
			busy = false;
			status = String(ready.error);
			return;
		}
		status = `Asking ${nodeLabel(node)}…`;
		const r = (await sidecarCall('knowledge_query', {
			node,
			listing_id: selected.listing_id,
			query_text: ask
		})) as Record<string, unknown>;
		busy = false;
		if (r.ok === false) {
			status = String(r.error);
			return;
		}
		answer = String(r.answer || '');
		if (r.code === 'llm_no_credit' || r.llm_available === false) {
			status = 'This Smart node cannot answer right now (AI provider unavailable). Pick another node.';
			await loadNodes();
			return;
		}
		status = r.tx_hash
			? `Paid ${bzt(cost)} · transaction ${String(r.tx_hash).slice(0, 10)}… is confirmed in the next block (~5 min).`
			: `Answer delivered, but the payment could not be submitted: ${JSON.stringify((r.tx as Record<string, unknown>)?.error ?? '')}`;
		await refreshWallet();
	}

	async function purchaseListing() {
		if (!node || !selected || busy) return;
		const price = Number(selected.purchase_price || 0);
		if (price <= 0) return;
		await refreshWallet();
		const total = price + NETWORK_FEE.purchase;
		if (balance != null && balance < total) {
			status = `Not enough BZT: buying costs ${bzt(total)}, your wallet has ${bzt(balance)}.`;
			return;
		}
		if (
			!confirm(
				`Buy “${selected.title}” for ${bzt(price)} + ${bzt(NETWORK_FEE.purchase)} network fee?\n` +
					`The indexed documents move into your workspace on ${nodeLabel(node)} and the listing closes.`
			)
		)
			return;
		busy = true;
		status = 'Buying…';
		const r = (await sidecarCall('knowledge_purchase', {
			node,
			listing_id: selected.listing_id
		})) as Record<string, unknown>;
		busy = false;
		status =
			r.ok === false
				? String(r.error)
				: r.tx_hash
					? `Bought · transaction ${String(r.tx_hash).slice(0, 10)}… The documents are now in your Ask workspace.`
					: 'Bought, but the payment transaction could not be submitted.';
		selected = null;
		await Promise.all([search(), loadWorkspace(), refreshWallet()]);
	}

	async function publish() {
		if (!node || busy) return;
		if (!pubSelected.length) {
			status = 'Select at least one indexed document.';
			return;
		}
		if (!pubTitle.trim()) {
			status = 'Give the listing a title buyers will understand.';
			return;
		}
		if (
			!confirm(
				`Publish “${pubTitle}” with ${pubSelected.length} document(s) on ${nodeLabel(node)}?\n` +
					`Network fee: ${bzt(NETWORK_FEE.publish)}. Buyers only receive answers, never the raw text.`
			)
		)
			return;
		busy = true;
		status = 'Publishing…';
		const r = (await sidecarCall('knowledge_publish', {
			node,
			title: pubTitle.trim(),
			description: pubDesc.trim(),
			file_ids: pubSelected,
			price_per_query: Number(pubPrice),
			purchase_price: Number(pubPurchase),
			tags: parseTags(pubTags)
		})) as Record<string, unknown>;
		busy = false;
		if (r.ok === false) {
			status = String(r.error);
			return;
		}
		status = r.tx_hash
			? `Published · transaction ${String(r.tx_hash).slice(0, 10)}… (confirmed in the next block).`
			: 'Published on the node, but the publish transaction could not be submitted.';
		pubTitle = pubDesc = pubTags = '';
		pubSelected = [];
		tab = 'mine';
		await Promise.all([loadMine(), search(), refreshWallet()]);
	}

	function startEdit(l: Listing) {
		editing = l.listing_id;
		edit = {
			title: l.title || '',
			description: l.description || '',
			tags: (l.tags || []).join(', '),
			price_per_query: Number(l.price_per_query || 0),
			purchase_price: Number(l.purchase_price || 0)
		};
	}

	async function mutate(l: Listing, method: 'knowledge_update' | 'knowledge_delete', fields?: Record<string, unknown>) {
		busy = true;
		const r = await sidecarCall(method, { node, listing_id: l.listing_id, fields });
		busy = false;
		status = r.ok === false ? String(r.error) : '';
		return r.ok !== false;
	}

	async function saveEdit(l: Listing) {
		const ok = await mutate(l, 'knowledge_update', {
			title: edit.title.trim(),
			description: edit.description.trim(),
			tags: parseTags(edit.tags),
			price_per_query: Number(edit.price_per_query),
			purchase_price: Number(edit.purchase_price)
		});
		if (ok) {
			editing = null;
			status = `Updated “${edit.title}”.`;
			await Promise.all([loadMine(), search()]);
		}
	}

	async function togglePause(l: Listing) {
		const next = l.status === 'active' ? 'paused' : 'active';
		if (await mutate(l, 'knowledge_update', { status: next })) {
			status = next === 'paused' ? `“${l.title}” is hidden from buyers.` : `“${l.title}” is visible again.`;
			await Promise.all([loadMine(), search()]);
		}
	}

	async function remove(l: Listing) {
		if (
			!confirm(
				`Delete “${l.title}”? Buyers can no longer find or ask it. Your indexed documents stay in your workspace, and past earnings stay on chain.`
			)
		)
			return;
		if (await mutate(l, 'knowledge_delete')) {
			status = `Deleted “${l.title}”.`;
			await Promise.all([loadMine(), search()]);
		}
	}

	let loaded = $state(false);
	$effect(() => {
		if (loaded) return;
		loaded = true;
		Promise.all([loadNodes(), refreshWallet()]).then(() =>
			Promise.all([loadWorkspace(), search(), loadMine()])
		);
	});
</script>

<h1>Knowledge</h1>
<p class="lead">
	Sell answers from your documents, or pay to ask questions about other people's documents. Nobody
	ever sees the raw files: the Smart node's AI reads them and returns only an answer.
</p>

<div class="steps">
	<div class="step">
		<div class="step-num">1</div>
		<div>
			<strong>Index documents in Ask</strong>
			<p>Ask → Browse → Index into node. You pay once per indexed passage. Indexed files stay private.</p>
		</div>
	</div>
	<div class="step">
		<div class="step-num">2</div>
		<div>
			<strong>Publish a listing</strong>
			<p>Pick indexed documents by name, set a price per question and, optionally, a sale price.</p>
		</div>
	</div>
	<div class="step">
		<div class="step-num">3</div>
		<div>
			<strong>Earn on chain</strong>
			<p>
				Each paid question gives you {SELLER_SHARE * 100}% (the Smart node keeps {100 - SELLER_SHARE * 100}%).
				A sale pays 100% and hands the documents to the buyer.
			</p>
		</div>
	</div>
</div>

<div class="card stack">
	<div class="row" style="gap:2rem; align-items:flex-end">
		<label class="field grow" style="max-width:30rem">
			<span>Smart node</span>
			<select onchange={(e) => switchNode((e.currentTarget as HTMLSelectElement).value)}>
				{#each nodes as n}
					<option value={String(n.node_id)} selected={n.node_id === node?.node_id}>
						{nodeLabel(n)}{n.llm_model ? ` · ${n.llm_model}` : ''}{nodeUsable(n) ? '' : ' · AI unavailable'}
					</option>
				{/each}
			</select>
		</label>
		<div class="field">
			<span>Wallet balance</span>
			<strong>{balance == null ? '—' : bzt(balance)}</strong>
		</div>
		<div class="field">
			<span>Your documents on this node</span>
			<strong>{workspaceFiles.length}</strong>
		</div>
	</div>
	<p class="meta" style="margin:0">
		Why pick a node? Each Smart node keeps its own encrypted document index and runs its own AI model.
		Listings, your indexed documents and your listings' questions all live on the node you select.
		{#if node && !nodeUsable(node)}
			<strong>This node's AI is unavailable right now: questions will fail, pick another node.</strong>
		{/if}
	</p>
</div>

<div class="tabs" role="tablist">
	<button class:active={tab === 'browse'} onclick={() => (tab = 'browse')}>Browse &amp; ask</button>
	<button class:active={tab === 'sell'} onclick={() => (tab = 'sell')}>Sell knowledge</button>
	<button class:active={tab === 'mine'} onclick={() => (tab = 'mine')}>
		My listings &amp; earnings{#if mine.length} ({mine.length}){/if}
	</button>
</div>

{#if status}<p class="callout">{status}</p>{/if}

{#if tab === 'browse'}
	<div class="row" style="margin-bottom:1rem">
		<input
			type="search"
			class="grow"
			bind:value={query}
			placeholder="Search listings by title or description"
			onkeydown={(e) => e.key === 'Enter' && search()}
		/>
		<button class="primary" onclick={search} disabled={busy}>Search</button>
	</div>
	<div class="split">
		<div class="stack">
			{#if listings.length === 0}
				<p class="meta">No listings on {nodeLabel(node)} match. Try another node or search term.</p>
			{/if}
			<div class="listings" style="grid-template-columns:1fr">
				{#each listings as item (item.listing_id)}
					<button
						class="listing"
						class:active={selected?.listing_id === item.listing_id}
						onclick={() => {
							selected = item;
							answer = '';
						}}
					>
						<div class="row" style="justify-content:space-between">
							<strong>{item.title}</strong>
							{#if item.seller_address === address}<span class="chip muted">Yours</span>{/if}
						</div>
						{#if item.description}<p class="lead">{item.description}</p>{/if}
						<div class="row">
							<span class="chip">{bzt(item.price_per_query)} / question</span>
							{#if Number(item.purchase_price || 0) > 0}
								<span class="chip">Buy {bzt(item.purchase_price)}</span>
							{/if}
							{#each item.tags || [] as t}<span class="chip muted">{t}</span>{/each}
						</div>
						<span class="meta" style="margin:0">
							{item.total_files ?? 0} document(s) · {item.total_queries ?? 0} questions answered
						</span>
					</button>
				{/each}
			</div>
		</div>
		<div class="card stack">
			{#if selected}
				<h2>{selected.title}</h2>
				{#if selected.description}<p class="lead">{selected.description}</p>{/if}
				<p class="meta" style="margin:0">
					Seller {String(selected.seller_address || '').slice(0, 14)}… · {selected.total_files ?? 0} document(s)
				</p>
				<label class="field">
					<span>Your question</span>
					<textarea bind:value={ask} placeholder="What do you want to know from these documents?"></textarea>
				</label>
				<div class="row">
					<button class="primary" onclick={queryListing} disabled={busy || !ask.trim()}>
						Ask · {bzt(selected.price_per_query)}
					</button>
					{#if Number(selected.purchase_price || 0) > 0 && selected.seller_address !== address}
						<button class="ghost" onclick={purchaseListing} disabled={busy}>
							Buy documents · {bzt(selected.purchase_price)}
						</button>
					{/if}
				</div>
				<p class="meta" style="margin:0">
					Plus a {bzt(NETWORK_FEE.query)} network fee per question. You pay only after the answer arrives.
				</p>
				{#if busy}<p class="meta">Working…</p>{/if}
				{#if answer}<pre>{answer}</pre>{/if}
			{:else}
				<h2>Ask a listing</h2>
				<p class="lead">
					Select a listing on the left. You ask a question, the Smart node's AI answers it using the
					seller's documents, and you pay the listing's price per question.
				</p>
			{/if}
		</div>
	</div>
{:else if tab === 'sell'}
	<div class="split">
		<div class="card stack">
			<h2>1 · Choose documents</h2>
			{#if workspaceFiles.length === 0}
				<p class="lead">
					You have no indexed documents on {nodeLabel(node)} yet. Index a PDF or text file in Ask
					first, on this same node.
				</p>
				<div><button class="primary" onclick={() => goto('/smart')}>Go to Ask to index</button></div>
			{:else}
				<WorkspacePicker files={workspaceFiles} bind:selected={pubSelected} />
				<p class="meta" style="margin:0">{pubSelected.length} selected</p>
			{/if}
		</div>
		<div class="card stack">
			<h2>2 · Describe and price</h2>
			<label class="field">
				<span>Title</span>
				<input type="text" bind:value={pubTitle} placeholder="e.g. EU AI Act compliance notes" />
			</label>
			<label class="field">
				<span>Description (what buyers can ask about)</span>
				<textarea bind:value={pubDesc}></textarea>
			</label>
			<label class="field">
				<span>Tags (comma separated)</span>
				<input type="text" bind:value={pubTags} placeholder="legal, compliance" />
			</label>
			<div class="row">
				<label class="field grow">
					<span>Price per question (BZT)</span>
					<input type="number" bind:value={pubPrice} step="0.01" min="0" />
				</label>
				<label class="field grow">
					<span>Sale price (BZT, 0 = not for sale)</span>
					<input type="number" bind:value={pubPurchase} step="0.1" min="0" />
				</label>
			</div>
			<p class="meta" style="margin:0">
				You earn {bzt(Number(pubPrice) * SELLER_SHARE)} per question.
				{#if Number(pubPurchase) > 0}A sale pays you {bzt(pubPurchase)} and transfers the documents to the buyer.{/if}
				Publishing costs a {bzt(NETWORK_FEE.publish)} network fee.
			</p>
			<div>
				<button class="primary" onclick={publish} disabled={busy || !pubSelected.length || !pubTitle.trim()}>
					Publish listing
				</button>
			</div>
		</div>
	</div>
{:else}
	<div class="stats" style="margin-bottom:1.25rem">
		<div class="stat"><div class="value">{bzt(totals.total_revenue)}</div><div class="label">Total earned</div></div>
		<div class="stat"><div class="value">{totals.queries ?? 0}</div><div class="label">Paid questions</div></div>
		<div class="stat"><div class="value">{totals.purchases ?? 0}</div><div class="label">Sales</div></div>
		<div class="stat"><div class="value">{activeCount} / {mine.length}</div><div class="label">Active listings on this node</div></div>
	</div>
	<p class="meta">
		Earnings count only payments confirmed on the blockchain; a new payment appears after the next block
		(~5 min).
		{#if statsError}Could not read earnings from the chain: {statsError}{/if}
	</p>

	{#if mine.length === 0}
		<p class="lead">
			You have no listings on {nodeLabel(node)}.
			<button class="ghost" onclick={() => (tab = 'sell')}>Publish one</button>
		</p>
	{/if}

	<div class="stack">
		{#each mine as l (l.listing_id)}
			{@const s = statsById.get(l.listing_id)}
			<div class="card stack">
				<div class="row" style="justify-content:space-between">
					<div class="row">
						<h2 style="margin:0">{l.title}</h2>
						<span class="chip {statusChip(l.status)}">{l.status}</span>
					</div>
					{#if l.status !== 'sold'}
						<div class="row">
							<button class="ghost" onclick={() => startEdit(l)} disabled={busy}>Edit</button>
							<button class="ghost" onclick={() => togglePause(l)} disabled={busy}>
								{l.status === 'active' ? 'Pause' : 'Resume'}
							</button>
							<button class="danger" onclick={() => remove(l)} disabled={busy}>Delete</button>
						</div>
					{/if}
				</div>

				{#if editing === l.listing_id}
					<label class="field"><span>Title</span><input type="text" bind:value={edit.title} /></label>
					<label class="field"><span>Description</span><textarea bind:value={edit.description}></textarea></label>
					<label class="field"><span>Tags</span><input type="text" bind:value={edit.tags} /></label>
					<div class="row">
						<label class="field grow">
							<span>Price per question (BZT)</span>
							<input type="number" bind:value={edit.price_per_query} step="0.01" min="0" />
						</label>
						<label class="field grow">
							<span>Sale price (BZT, 0 = not for sale)</span>
							<input type="number" bind:value={edit.purchase_price} step="0.1" min="0" />
						</label>
					</div>
					<div class="row">
						<button class="primary" onclick={() => saveEdit(l)} disabled={busy || !edit.title.trim()}>Save</button>
						<button class="ghost" onclick={() => (editing = null)}>Cancel</button>
					</div>
				{:else}
					{#if l.description}<p class="lead" style="margin:0">{l.description}</p>{/if}
					<div class="row">
						<span class="chip">{bzt(l.price_per_query)} / question</span>
						{#if Number(l.purchase_price || 0) > 0}<span class="chip">Sale {bzt(l.purchase_price)}</span>{/if}
						{#each l.tags || [] as t}<span class="chip muted">{t}</span>{/each}
					</div>
				{/if}

				<div class="stats">
					<div class="stat"><div class="value">{bzt(s?.total_revenue)}</div><div class="label">Earned</div></div>
					<div class="stat">
						<div class="value">{s?.queries ?? 0}</div>
						<div class="label">Paid questions · {l.total_queries ?? 0} answered</div>
					</div>
					<div class="stat"><div class="value">{s?.unique_buyers ?? 0}</div><div class="label">Distinct buyers</div></div>
					<div class="stat"><div class="value">{s?.purchases ?? 0}</div><div class="label">Sales</div></div>
				</div>

				<p class="meta" style="margin:0">
					Documents:
					{#each l.files || [] as f, i}{i ? ', ' : ''}<strong>{f.file_name || f.file_id.slice(0, 8)}</strong>{/each}
					· published {String(l.created_at || '').slice(0, 10)} · id {l.listing_id.slice(0, 8)}
				</p>
			</div>
		{/each}
	</div>

	{#if offNode.length}
		<h2 style="margin-top:1.5rem">Earnings from listings not on this node</h2>
		<p class="meta">Listings published on another Smart node, or deleted. Switch node above to manage them.</p>
		<div class="stack">
			{#each offNode as s (s.listing_id)}
				<div class="row card" style="justify-content:space-between">
					<span>Listing {s.listing_id.slice(0, 8)}…</span>
					<span class="meta" style="margin:0">
						{s.queries} paid questions · {s.purchases} sales · <strong>{bzt(s.total_revenue)}</strong>
					</span>
				</div>
			{/each}
		</div>
	{/if}
{/if}
