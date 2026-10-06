<script lang="ts">
	import { sidecarCall } from '#lib';
	import { open } from '@tauri-apps/plugin-dialog';

	type Upload = Record<string, unknown> & {
		file_id?: string;
		file_name?: string;
		file_size?: number;
		visibility?: string;
		marketplace_price?: string;
		num_chunks?: number;
	};

	let path = $state('');
	let visibility = $state('private');
	let duration = $state(5);
	let nodeCount = $state(3);
	let price = $state(0);
	let tags = $state('');
	let estimate = $state<Record<string, unknown> | null>(null);
	let uploads = $state<Upload[]>([]);
	let status = $state('');
	let busy = $state(false);
	let loaded = $state(false);

	async function refresh() {
		const r = await sidecarCall('asset_list');
		uploads = ((r.uploads as Upload[]) || []) as Upload[];
		if (r.ok === false) status = String(r.error);
	}

	$effect(() => {
		if (loaded) return;
		loaded = true;
		refresh();
	});

	async function browse() {
		try {
			const picked = await open({ multiple: false });
			if (typeof picked === 'string') {
				path = picked;
				await recalc();
			}
		} catch (err) {
			status = String(err);
		}
	}

	async function recalc() {
		if (!path) return;
		estimate = await sidecarCall('asset_upload_estimate', {
			path,
			duration,
			node_count: nodeCount
		});
	}

	async function upload() {
		if (!path) return;
		busy = true;
		status = 'Encrypting, storing chunks on Storage nodes, then registering the upload TX…';
		const r = await sidecarCall('asset_upload', {
			path,
			visibility,
			duration,
			node_count: nodeCount,
			price,
			tags: tags
				.split(',')
				.map((s) => s.trim())
				.filter(Boolean)
		});
		busy = false;
		if (r.ok === false) {
			status = String(r.error);
			return;
		}
		status = `Stored ${r.file_name} · ${r.chunks} chunks · ${r.cost} BZT · tx ${String(r.tx_hash || '').slice(0, 12)}`;
		await refresh();
	}

	async function download(fileId: string) {
		try {
			const dir = await open({ directory: true, multiple: false });
			if (typeof dir !== 'string') return;
			busy = true;
			status = 'Fetching chunks and decrypting…';
			const r = await sidecarCall('asset_download', { file_id: fileId, dest_dir: dir });
			busy = false;
			status = r.ok === false ? String(r.error) : `Saved ${r.path}`;
		} catch (err) {
			busy = false;
			status = String(err);
		}
	}
</script>

<h1>Files</h1>
<p class="lead">
	This is digital-asset storage: AES-256-GCM encryption, 1 MiB chunks on BeezStorage, a guardian DAM,
	and an on-chain <code>upload</code> transaction. It is not the same as Ask → Index, which only
	embeds text into a Smart node for RAG. Store the file here first; index a copy in Ask later if you
	want Tokenized Intelligence over it.
</p>

<div class="card" style="max-width:none">
	<strong>Upload to Storage + DAM</strong>
	<p class="meta">Needs a wallet with enough BZT for chunks × price_per_chunk × years.</p>
	<div class="row">
		<input type="text" bind:value={path} placeholder="Absolute path" style="flex:1;min-width:12rem" />
		<button class="ghost" onclick={browse}>Browse</button>
	</div>
	<div class="row" style="margin-top:0.6rem">
		<label class="meta">Visibility
			<select bind:value={visibility} onchange={recalc}>
				<option value="private">private</option>
				<option value="public">public</option>
			</select>
		</label>
		<label class="meta">Years
			<select bind:value={duration} onchange={recalc}>
				<option value={3}>3</option>
				<option value={5}>5</option>
				<option value={7}>7</option>
				<option value={10}>10</option>
			</select>
		</label>
		<label class="meta">Storage nodes
			<select bind:value={nodeCount} onchange={recalc}>
				<option value={1}>1</option>
				<option value={3}>3</option>
				<option value={6}>6</option>
			</select>
		</label>
		<label class="meta">Sell price (BZT)
			<input type="number" bind:value={price} min="0" step="0.1" style="width:6rem" />
		</label>
	</div>
	<input
		type="text"
		bind:value={tags}
		placeholder="tags, comma separated"
		style="width:100%;margin-top:0.6rem"
	/>
	{#if estimate?.ok}
		<p class="meta">
			~{estimate.chunks} encrypted chunks · {estimate.storage_nodes} Storage nodes ·
			<strong>{Number(estimate.estimated_cost || 0).toFixed(2)} BZT</strong>
			{#if estimate.guardian_dam_id} · DAM {String(estimate.guardian_dam_id)}{/if}
		</p>
	{:else if estimate?.ok === false}
		<p class="meta" style="color:var(--danger)">{String(estimate.error)}</p>
	{/if}
	<div class="row" style="margin-top:0.75rem">
		<button class="ghost" onclick={recalc} disabled={!path}>Estimate cost</button>
		<button class="primary" onclick={upload} disabled={busy || !path}>Encrypt and store</button>
	</div>
</div>

<div class="card" style="margin-top:1rem;max-width:none">
	<strong>My files</strong>
	<button class="ghost" onclick={refresh}>Refresh</button>
	{#if uploads.length === 0}
		<p class="meta">No uploads for this wallet yet.</p>
	{/if}
	<ul class="node-list">
		{#each uploads as u}
			<li>
				<strong>{String(u.file_name || u.file_id)}</strong>
				<span class="caps">
					{u.visibility || '—'} · {u.num_chunks ?? '?'} chunks
					{#if u.marketplace_price} · {u.marketplace_price}{/if}
				</span>
				<button class="ghost" onclick={() => download(String(u.file_id))}>Download</button>
			</li>
		{/each}
	</ul>
</div>

{#if status}<p class="meta">{status}</p>{/if}

<style>
	.node-list {
		list-style: none;
		padding: 0;
	}
	.node-list li {
		padding: 0.5rem 0;
		border-bottom: 1px solid var(--border);
		display: flex;
		gap: 0.75rem;
		align-items: center;
		flex-wrap: wrap;
	}
	.caps {
		color: var(--muted);
		font-size: 0.8rem;
	}
</style>
