<script lang="ts">
	import { sidecarCall, onLiveTick, Pager } from '#lib';
	import WorldMap from '#lib/WorldMap.svelte';

	type Node = Record<string, unknown>;
	type Loc = { lat: number; lon: number; city?: string; country?: string; source?: string };

	const TYPES: Record<string, string> = {
		chain: 'Chain validator',
		storage: 'Storage',
		smart: 'Smart (Ask)',
		manager: 'DAM manager'
	};
	const PAGE = 12;

	let nodes = $state<Node[]>([]);
	let errors = $state<unknown[]>([]);
	let geoError = $state('');
	let loading = $state(true);
	let typeFilter = $state('');
	let query = $state('');
	let offset = $state(0);
	let selected = $state('');

	async function refresh() {
		const r = await sidecarCall('network_map');
		loading = false;
		nodes = (r.nodes as Node[]) || [];
		errors = (r.errors as unknown[]) || [];
		geoError = r.geo_error ? String(r.geo_error) : '';
	}

	$effect(() => {
		refresh();
		return onLiveTick(refresh);
	});

	const loc = (n: Node) => (n.location as Loc | null) || null;
	const filtered = $derived(
		nodes.filter((n) => {
			if (typeFilter && n.node_type !== typeFilter) return false;
			const q = query.trim().toLowerCase();
			if (!q) return true;
			const l = loc(n);
			return [n.node_id, n.wallet_address, n.node_type, l?.city, l?.country]
				.map((v) => String(v || '').toLowerCase())
				.some((v) => v.includes(q));
		})
	);
	const pins = $derived(
		filtered
			.filter((n) => loc(n))
			.map((n) => {
				const l = loc(n)!;
				return {
					id: String(n.node_id),
					lon: Number(l.lon),
					lat: Number(l.lat),
					type: String(n.node_type),
					title: `${TYPES[String(n.node_type)] || n.node_type} · ${l.city || ''} ${l.country || ''}`
				};
			})
	);
	const counts = $derived(
		Object.keys(TYPES).map((t) => ({ t, n: nodes.filter((x) => x.node_type === t).length }))
	);
	const countries = $derived(new Set(nodes.map((n) => loc(n)?.country).filter(Boolean)).size);
	const sel = $derived(nodes.find((n) => n.node_id === selected) || null);

	function pick(id: string) {
		const i = filtered.findIndex((n) => n.node_id === id);
		if (i >= 0) offset = Math.floor(i / PAGE) * PAGE;
	}

	function copy(text: unknown) {
		navigator.clipboard?.writeText(String(text));
	}
</script>

<h1>Network</h1>
<p class="lead">
	Every node registered with the Directory, where it runs and which wallet receives its rewards. Click a dot
	or a row for details.
</p>

<div class="stats">
	{#each counts as c (c.t)}
		<div class="stat"><div class="value">{c.n}</div><div class="label">{TYPES[c.t]} nodes</div></div>
	{/each}
	<div class="stat"><div class="value">{countries}</div><div class="label">Countries</div></div>
</div>

<div class="card stack" style="margin-top:1rem">
	<div class="legend">
		{#each Object.entries(TYPES) as [t, label]}<span><i class={t}></i>{label}</span>{/each}
	</div>
	<WorldMap {pins} bind:selected onselect={pick} />
	{#if geoError}<p class="meta">Some locations could not be looked up ({geoError}); nodes' self-reported positions are used instead.</p>{/if}
	<p class="meta">Locations come from each node's public IP address (approximate, city level).</p>
</div>

<div class="split" style="margin-top:1rem">
	<div class="card">
		<div class="toolbar">
			<label class="field">
				<span>Type</span>
				<select bind:value={typeFilter} onchange={() => (offset = 0)}>
					<option value="">All types</option>
					{#each Object.entries(TYPES) as [t, label]}<option value={t}>{label}</option>{/each}
				</select>
			</label>
			<label class="field grow">
				<span>Search (node, wallet, city, country)</span>
				<input type="search" bind:value={query} oninput={() => (offset = 0)} placeholder="Search…" />
			</label>
		</div>
		{#if loading}<p class="meta">Loading the Directory roster…</p>{/if}
		{#if !loading && filtered.length === 0}<p class="meta">No nodes match.</p>{/if}
		<ul class="list">
			{#each filtered.slice(offset, offset + PAGE) as n (n.node_id)}
				<li>
					<button class="rowlink" onclick={() => (selected = String(n.node_id))}>
						<span class="chip {n.node_id === selected ? '' : 'muted'}">{TYPES[String(n.node_type)] || String(n.node_type)}</span>
						<strong class="mono">{n.wallet_address ? String(n.wallet_address) : 'no reward wallet published'}</strong>
						<span class="sub">{loc(n) ? `${loc(n)?.city || ''}, ${loc(n)?.country || ''}` : 'location unknown'}</span>
					</button>
				</li>
			{/each}
		</ul>
		<Pager total={filtered.length} limit={PAGE} bind:offset />
	</div>

	<div class="card stack">
		{#if sel}
			<h2 style="margin:0">{TYPES[String(sel.node_type)] || String(sel.node_type)}</h2>
			<dl class="kv">
				<dt>Wallet</dt>
				<dd class="mono">
					{#if sel.wallet_address}
						<a href={`/blockchain?wallet=${sel.wallet_address}`}>{String(sel.wallet_address)}</a>
						<button class="ghost" onclick={() => copy(sel?.wallet_address)}>Copy</button>
					{:else}
						Not published by this node type.
					{/if}
				</dd>
				<dt>Node</dt><dd class="mono">{String(sel.node_id)}</dd>
				<dt>Location</dt><dd>{loc(sel) ? `${loc(sel)?.city || '—'}, ${loc(sel)?.country || '—'}` : 'Unknown'}</dd>
				{#if Array.isArray(sel.capabilities) && sel.capabilities.length}<dt>Capabilities</dt><dd>{sel.capabilities.join(', ')}</dd>{/if}
				{#if Array.isArray(sel.models) && sel.models.length}<dt>Models</dt><dd>{sel.models.join(', ')}</dd>{/if}
				{#if sel.price_per_query != null}<dt>Price per question</dt><dd>{String(sel.price_per_query)} BZT</dd>{/if}
				{#if sel.price_per_embedding != null}<dt>Price per indexed chunk</dt><dd>{String(sel.price_per_embedding)} BZT</dd>{/if}
				{#if sel.price_per_chunk != null}<dt>Storage price per chunk</dt><dd>{String(sel.price_per_chunk)} BZT/period</dd>{/if}
				{#if sel.reputation != null}<dt>Reputation</dt><dd>{String(sel.reputation)}</dd>{/if}
				{#if sel.banned}<dt>Status</dt><dd class="error">Banned</dd>{/if}
			</dl>
		{:else}
			<p class="meta">Select a node on the map or in the list to see its wallet, location and prices.</p>
		{/if}
		{#if errors.length}
			<p class="meta">Some Directory nodes did not answer: {errors.map(String).join('; ')}</p>
		{/if}
	</div>
</div>
