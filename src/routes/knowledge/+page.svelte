<script lang="ts">
	import { sidecarCall } from '#lib';

	type SmartNode = Record<string, unknown> & {
		node_id?: string;
		instance_id?: string;
		label?: string;
		llm_model?: string;
		llm_available?: boolean;
		available?: boolean;
	};

	type Listing = Record<string, unknown> & {
		listing_id?: string;
		title?: string;
		description?: string;
		price_per_query?: number;
		purchase_price?: number;
		seller_address?: string;
		tags?: string[];
		file_ids?: string[];
		total_files?: number;
		total_chunks?: number;
	};

	let nodes = $state<SmartNode[]>([]);
	let node = $state<SmartNode | null>(null);
	let query = $state('');
	let listings = $state<Listing[]>([]);
	let mine = $state<Listing[]>([]);
	let selected = $state<Listing | null>(null);
	let ask = $state('');
	let answer = $state('');
	let status = $state('');
	let busy = $state(false);
	let pubTitle = $state('');
	let pubDesc = $state('');
	let pubFiles = $state('');
	let pubPrice = $state(1);
	let pubPurchase = $state(0);
	let workspaceIds = $state<string[]>([]);
	let balance = $state<number | null>(null);

	function nodeLabel(n: SmartNode | null): string {
		if (!n) return 'No node';
		return String(n.label || n.instance_id || n.node_id || 'Smart');
	}

	async function refreshBalance() {
		const ledger = await sidecarCall('wallet_ledger');
		if (ledger.ok !== false && ledger.balance != null && ledger.balance !== '') {
			const n = Number(ledger.balance);
			balance = Number.isNaN(n) ? null : n;
		} else {
			balance = null;
		}
	}

	async function loadNodes() {
		const r = (await sidecarCall('list_smart_nodes')) as Record<string, unknown>;
		nodes = ((r.nodes as SmartNode[]) || []).filter((n) => n.node_id !== 'local_minicpm');
		if (!node && nodes.length) {
			const usable = nodes.find((n) => n.llm_available !== false && n.available !== false);
			node = usable || nodes[0];
		}
		if (node) {
			const match = nodes.find((n) => n.node_id === node?.node_id);
			if (match) node = match;
		}
	}

	async function loadWorkspaceFiles() {
		if (!node) {
			workspaceIds = [];
			return;
		}
		const r = (await sidecarCall('workspace_stats', { node })) as Record<string, unknown>;
		const files = (r.files as Record<string, unknown>[]) || (r.file_ids as string[]) || [];
		if (Array.isArray(files) && files.length && typeof files[0] === 'string') {
			workspaceIds = files as string[];
		} else if (Array.isArray(files)) {
			workspaceIds = files
				.map((f) => String((f as Record<string, unknown>).file_id || ''))
				.filter(Boolean);
		} else {
			workspaceIds = [];
		}
	}

	async function search() {
		if (!node) return;
		status = 'Searching marketplace…';
		const r = (await sidecarCall('knowledge_search', { node, query })) as Record<string, unknown>;
		listings = (r.listings as Listing[]) || [];
		status = r.ok === false ? String(r.error) : `${listings.length} listings on ${nodeLabel(node)}`;
	}

	async function loadMine() {
		if (!node) return;
		const r = (await sidecarCall('knowledge_mine', { node })) as Record<string, unknown>;
		mine = (r.listings as Listing[]) || [];
	}

	async function queryListing() {
		if (!node || !selected || !ask.trim() || busy) return;
		const cost = Number(selected.price_per_query || 0);
		await refreshBalance();
		if (balance != null && balance < cost) {
			status = `Insufficient balance: need ${cost} BZT, wallet has ${balance} BZT.`;
			return;
		}
		if (
			!confirm(
				`Pay ~${cost} BZT to query “${selected.title}” on ${nodeLabel(node)}?\n` +
					(balance != null ? `Wallet balance: ${balance} BZT` : 'Balance unknown')
			)
		) {
			return;
		}
		busy = true;
		status = 'Preparing embedding model…';
		const ready = await sidecarCall('embed_ensure');
		if (ready.ok === false) {
			busy = false;
			status = String(ready.error);
			return;
		}
		status = 'Pay-per-query on listing…';
		const r = (await sidecarCall('knowledge_query', {
			node,
			listing_id: selected.listing_id,
			query_text: ask
		})) as Record<string, unknown>;
		busy = false;
		answer = String(r.answer || r.error || '');
		if (r.code === 'llm_no_credit' || r.llm_available === false) {
			status = 'Node LLM has no provider credits — pick another Smart node.';
			await loadNodes();
			return;
		}
		status = r.tx_hash
			? `Answer ready · settled ${String(r.tx_hash).slice(0, 10)}…`
			: r.ok === false
				? String(r.error)
				: 'done';
		await refreshBalance();
	}

	async function purchaseListing() {
		if (!node || !selected || busy) return;
		const price = Number(selected.purchase_price || 0);
		if (price <= 0) {
			status = 'This listing is not for sale.';
			return;
		}
		await refreshBalance();
		if (balance != null && balance < price) {
			status = `Insufficient balance: need ${price} BZT, wallet has ${balance} BZT.`;
			return;
		}
		if (
			!confirm(
				`Buy ownership of “${selected.title}” for ${price} BZT?\n` +
					(balance != null ? `Wallet balance: ${balance} BZT` : 'Balance unknown')
			)
		) {
			return;
		}
		busy = true;
		status = 'Purchasing listing…';
		const r = (await sidecarCall('knowledge_purchase', {
			node,
			listing_id: selected.listing_id
		})) as Record<string, unknown>;
		busy = false;
		status =
			r.ok === false
				? String(r.error)
				: r.tx_hash
					? `Purchased · settled ${String(r.tx_hash).slice(0, 10)}…`
					: 'Purchase completed (check settlement).';
		await search();
		await loadMine();
		await refreshBalance();
	}

	async function publish() {
		if (!node || busy) return;
		const file_ids = pubFiles
			.split(/[,\s]+/)
			.map((s) => s.trim())
			.filter(Boolean);
		if (!pubTitle.trim() || !file_ids.length) {
			status = 'Title and at least one indexed file_id are required.';
			return;
		}
		busy = true;
		status = 'Publishing listing…';
		const r = (await sidecarCall('knowledge_publish', {
			node,
			title: pubTitle,
			description: pubDesc,
			file_ids,
			price_per_query: pubPrice,
			purchase_price: pubPurchase,
			tags: []
		})) as Record<string, unknown>;
		busy = false;
		status =
			r.ok === false
				? String(r.error)
				: r.tx_hash
					? `Published ${String(r.listing_id || '').slice(0, 8)}… · tx ${String(r.tx_hash).slice(0, 10)}…`
					: JSON.stringify(r);
		await loadMine();
		await search();
	}

	function useWorkspaceFiles() {
		if (!workspaceIds.length) {
			status = 'No indexed files on this node yet. Index in Ask first.';
			return;
		}
		pubFiles = workspaceIds.join(',');
	}

	let loaded = $state(false);
	$effect(() => {
		if (loaded) return;
		loaded = true;
		loadNodes().then(async () => {
			await refreshBalance();
			await loadWorkspaceFiles();
			await search();
			await loadMine();
		});
	});
</script>

<h1>Knowledge</h1>
<p class="lead">
	Marketplace for listed document collections. Pay BZT per query (answers only) or buy ownership when
	the seller sets a purchase price. Your Ask workspace stays private until you publish file IDs here.
</p>

{#if balance != null}
	<p class="meta">Wallet balance: <strong>{balance}</strong> BZT</p>
{/if}

<div class="row" style="margin-bottom:1rem">
	<select
		onchange={async (e) => {
			const id = (e.currentTarget as HTMLSelectElement).value;
			node = nodes.find((n) => n.node_id === id) || node;
			await loadWorkspaceFiles();
			await search();
			await loadMine();
		}}
	>
		{#each nodes as n}
			<option value={String(n.node_id)} selected={n.node_id === node?.node_id}>
				{nodeLabel(n)}
				{#if n.llm_available === false || n.available === false} (LLM unavailable){/if}
			</option>
		{/each}
	</select>
	<input type="text" bind:value={query} placeholder="Search listings" />
	<button class="primary" onclick={search} disabled={busy}>Search</button>
</div>

<div class="listings">
	{#each listings as item}
		<button class="listing" class:active={selected?.listing_id === item.listing_id} onclick={() => (selected = item)}>
			<strong>{item.title}</strong>
			<p class="lead">{item.description}</p>
			<div class="meta">
				{item.price_per_query ?? 0} BZT / query
				{#if Number(item.purchase_price || 0) > 0} · buy {item.purchase_price} BZT{/if}
				{#if item.total_files} · {item.total_files} files{/if}
				{#if item.tags?.length} · {(item.tags || []).join(', ')}{/if}
			</div>
		</button>
	{/each}
</div>

{#if selected}
	<div class="card" style="margin-top:1rem; max-width:none">
		<h2>{selected.title}</h2>
		<p class="meta">
			Seller {String(selected.seller_address || '').slice(0, 12)}…
			· listing {String(selected.listing_id || '').slice(0, 8)}…
		</p>
		<textarea bind:value={ask} placeholder="Question against this listing"></textarea>
		<div class="row" style="margin-top:0.5rem">
			<button class="primary" onclick={queryListing} disabled={busy}
				>Pay-per-query · {selected.price_per_query ?? 0} BZT</button
			>
			{#if Number(selected.purchase_price || 0) > 0}
				<button class="ghost" onclick={purchaseListing} disabled={busy}
					>Buy ownership · {selected.purchase_price} BZT</button
				>
			{/if}
		</div>
		{#if answer}<pre>{answer}</pre>{/if}
	</div>
{/if}

<div class="card" style="margin-top:1.25rem; max-width:none">
	<h2>Publish from your workspace</h2>
	<p class="lead">
		File IDs must already be indexed on <strong>{nodeLabel(node)}</strong> (Ask → Index).
		{#if workspaceIds.length}
			{workspaceIds.length} file(s) available.
		{/if}
	</p>
	<div class="row">
		<input type="text" bind:value={pubTitle} placeholder="Title" />
		<input type="number" bind:value={pubPrice} title="BZT per query" step="0.1" min="0" />
		<input type="number" bind:value={pubPurchase} title="Purchase price (0 = not for sale)" step="0.1" min="0" />
	</div>
	<p class="meta">Price/query · Purchase price (0 = query-only)</p>
	<div class="row">
		<input
			type="text"
			bind:value={pubFiles}
			placeholder="file_id,file_id"
			style="flex:1;min-width:12rem"
		/>
		<button class="ghost" onclick={useWorkspaceFiles}>Use workspace files</button>
	</div>
	<textarea bind:value={pubDesc} placeholder="Description"></textarea>
	<button class="primary" style="margin-top:0.5rem" onclick={publish} disabled={busy}>Publish listing</button>
</div>

{#if mine.length}
	<h2>Your listings</h2>
	<div class="listings">
		{#each mine as item}
			<button class="listing" onclick={() => (selected = item)}>
				<strong>{item.title}</strong>
				<div class="meta">
					{item.listing_id}
					· {item.price_per_query ?? 0} BZT / query
					{#if Number(item.purchase_price || 0) > 0} · sale {item.purchase_price} BZT{/if}
				</div>
			</button>
		{/each}
	</div>
{/if}

{#if status}<p class="meta">{status}</p>{/if}
