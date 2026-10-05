<script lang="ts">
	import { sidecarCall } from '#lib';
	import { goto } from '$app/navigation';

	type Listing = Record<string, unknown> & {
		listing_id?: string;
		title?: string;
		description?: string;
		price_per_query?: number;
		purchase_price?: number;
		seller_address?: string;
		tags?: string[];
	};

	let nodes = $state<Record<string, unknown>[]>([]);
	let node = $state<Record<string, unknown> | null>(null);
	let query = $state('');
	let listings = $state<Listing[]>([]);
	let mine = $state<Listing[]>([]);
	let selected = $state<Listing | null>(null);
	let ask = $state('');
	let answer = $state('');
	let status = $state('');
	let pubTitle = $state('');
	let pubDesc = $state('');
	let pubFiles = $state('');
	let pubPrice = $state(1);

	async function loadNodes() {
		const r = (await sidecarCall('list_smart_nodes')) as Record<string, unknown>;
		nodes = ((r.nodes as Record<string, unknown>[]) || []).filter((n) => n.node_id !== 'local_minicpm');
		if (!node && nodes.length) node = nodes[0];
	}

	async function search() {
		if (!node) return;
		status = 'Searching marketplace…';
		const r = (await sidecarCall('knowledge_search', { node, query })) as Record<string, unknown>;
		listings = (r.listings as Listing[]) || [];
		status = r.ok === false ? String(r.error) : `${listings.length} listings`;
	}

	async function loadMine() {
		if (!node) return;
		const r = (await sidecarCall('knowledge_mine', { node })) as Record<string, unknown>;
		mine = (r.listings as Listing[]) || [];
	}

	async function queryListing() {
		if (!node || !selected || !ask.trim()) return;
		status = 'Pay-per-query on listing…';
		const r = (await sidecarCall('knowledge_query', {
			node,
			listing_id: selected.listing_id,
			query_text: ask
		})) as Record<string, unknown>;
		answer = String(r.answer || r.error || '');
		status = r.tx_hash ? `settled ${r.tx_hash}` : String(r.error || 'done');
	}

	async function publish() {
		if (!node) return;
		const file_ids = pubFiles
			.split(',')
			.map((s) => s.trim())
			.filter(Boolean);
		status = 'Publishing listing…';
		const r = await sidecarCall('knowledge_publish', {
			node,
			title: pubTitle,
			description: pubDesc,
			file_ids,
			price_per_query: pubPrice,
			tags: []
		});
		status = JSON.stringify(r);
		await loadMine();
		await search();
	}

	function openInAsk() {
		if (!selected) return;
		goto(`/smart?listing=${encodeURIComponent(String(selected.listing_id))}`);
	}

	let loaded = $state(false);
	$effect(() => {
		if (loaded) return;
		loaded = true;
		loadNodes().then(() => {
			search();
			loadMine();
		});
	});
</script>

<h1>Knowledge</h1>
<p class="lead">
	The knowledge market is other people’s listed collections. You pay BZT per query (answers only) or
	buy ownership. Your workspace (Ask) stays private until you publish it here.
</p>

<div class="row" style="margin-bottom:1rem">
	<select
		onchange={(e) => {
			const id = (e.currentTarget as HTMLSelectElement).value;
			node = nodes.find((n) => n.node_id === id) || node;
		}}
	>
		{#each nodes as n}
			<option value={String(n.node_id)}>{String(n.node_id)}</option>
		{/each}
	</select>
	<input type="text" bind:value={query} placeholder="Search listings" />
	<button class="primary" onclick={search}>Search</button>
</div>

<div class="listings">
	{#each listings as item}
		<button class="listing" onclick={() => (selected = item)}>
			<strong>{item.title}</strong>
			<p class="lead">{item.description}</p>
			<div class="meta">
				{item.price_per_query} BZT / query
				{#if item.purchase_price} · buy {item.purchase_price} BZT{/if}
				{#if item.tags?.length} · {(item.tags || []).join(', ')}{/if}
			</div>
		</button>
	{/each}
</div>

{#if selected}
	<div class="card" style="margin-top:1rem; max-width:none">
		<h2>{selected.title}</h2>
		<textarea bind:value={ask} placeholder="Question against this listing"></textarea>
		<div class="row" style="margin-top:0.5rem">
			<button class="primary" onclick={queryListing}>Pay-per-query</button>
			<button class="ghost" onclick={openInAsk}>Open in Ask</button>
		</div>
		{#if answer}<pre>{answer}</pre>{/if}
	</div>
{/if}

<div class="card" style="margin-top:1.25rem; max-width:none">
	<h2>Publish from your workspace</h2>
	<p class="lead">File IDs must already be indexed on the selected Smart node (Ask → Index).</p>
	<div class="row">
		<input type="text" bind:value={pubTitle} placeholder="Title" />
		<input type="number" bind:value={pubPrice} />
	</div>
	<input type="text" bind:value={pubFiles} placeholder="file_id,file_id" style="width:100%;margin:0.5rem 0" />
	<textarea bind:value={pubDesc} placeholder="Description"></textarea>
	<button class="primary" style="margin-top:0.5rem" onclick={publish}>Publish listing</button>
</div>

{#if mine.length}
	<h2>Your listings</h2>
	<div class="listings">
		{#each mine as item}
			<div class="listing">
				<strong>{item.title}</strong>
				<div class="meta">{item.listing_id}</div>
			</div>
		{/each}
	</div>
{/if}

{#if status}<p class="meta">{status}</p>{/if}
