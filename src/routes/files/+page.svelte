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

	type OwnershipReq = Record<string, unknown> & {
		request_id?: string;
		request_tx_hash?: string;
		file_id?: string;
		file_name?: string;
		asking_price?: string | number;
		current_owner?: string;
		current_owner_address?: string;
		new_owner?: string;
		new_owner_address?: string;
		status?: string;
		type?: string;
	};

	function sellerOf(r: OwnershipReq): string {
		return String(r.current_owner || r.current_owner_address || '');
	}
	function buyerOf(r: OwnershipReq): string {
		return String(r.new_owner || r.new_owner_address || '');
	}

	let path = $state('');
	let visibility = $state('private');
	let duration = $state(5);
	let nodeCount = $state(3);
	let price = $state(0);
	let tags = $state('');
	let estimate = $state<Record<string, unknown> | null>(null);
	let uploads = $state<Upload[]>([]);
	let incoming = $state<OwnershipReq[]>([]);
	let outgoing = $state<OwnershipReq[]>([]);
	let status = $state('');
	let busy = $state(false);
	let loaded = $state(false);
	let transferFileId = $state('');
	let transferTo = $state('');
	let transferPrice = $state(0);
	let transferMsg = $state('');

	function reqId(r: OwnershipReq): string {
		return String(r.request_id || r.request_tx_hash || '');
	}

	function priceNum(r: OwnershipReq): number {
		const v = r.asking_price;
		if (typeof v === 'number') return v;
		if (typeof v === 'string') {
			const n = Number(v.replace(/BZT/gi, '').trim());
			return Number.isNaN(n) ? 0 : n;
		}
		return 0;
	}

	async function refresh() {
		const r = await sidecarCall('asset_list');
		uploads = ((r.uploads as Upload[]) || []) as Upload[];
		if (r.ok === false) status = String(r.error);
		const p = await sidecarCall('ownership_pending');
		if (p.ok !== false) {
			incoming = ((p.incoming as OwnershipReq[]) || []) as OwnershipReq[];
			outgoing = ((p.outgoing as OwnershipReq[]) || []) as OwnershipReq[];
		}
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

	function startTransfer(fileId: string) {
		transferFileId = fileId;
		transferTo = '';
		transferPrice = 0;
		transferMsg = '';
	}

	async function submitTransfer() {
		if (!transferFileId || !transferTo.trim() || busy) return;
		if (
			!confirm(
				`Offer ownership of ${transferFileId.slice(0, 8)}… to ${transferTo.trim()} for ${transferPrice} BZT?\n` +
					'The encryption key will be wrapped with ECDH so the buyer can decrypt after accept.'
			)
		) {
			return;
		}
		busy = true;
		status = 'Sending ownership_request…';
		const r = await sidecarCall('ownership_transfer', {
			file_id: transferFileId,
			new_owner: transferTo.trim(),
			asking_price: transferPrice,
			message: transferMsg
		});
		busy = false;
		if (r.ok === false) {
			status = typeof r.error === 'string' ? r.error : JSON.stringify(r.error);
			return;
		}
		status = `Transfer offered · request ${String(r.request_id || r.tx_hash || '').slice(0, 12)}…`;
		transferFileId = '';
		await refresh();
	}

	async function acceptIncoming(r: OwnershipReq) {
		const id = reqId(r);
		const price = priceNum(r);
		if (
			!confirm(
				`Accept ownership of “${r.file_name || r.file_id}” for ${price} BZT?\n` +
					'BZT will be transferred to the seller on-chain.'
			)
		) {
			return;
		}
		busy = true;
		status = 'Accepting ownership…';
		const res = await sidecarCall('ownership_accept', {
			request_id: id,
			file_id: r.file_id,
			asking_price: price
		});
		busy = false;
		status =
			res.ok === false
				? String(res.error)
				: `Accepted · tx ${String(res.tx_hash || '').slice(0, 12)}…`;
		await refresh();
	}

	async function sellerAcceptOutgoing(r: OwnershipReq) {
		const id = reqId(r);
		const price = priceNum(r);
		if (
			!confirm(
				`Approve buyer ${buyerOf(r)} for “${r.file_name || r.file_id}” at ${price} BZT?\n` +
					'Your file key will be ECDH-wrapped for the buyer.'
			)
		) {
			return;
		}
		busy = true;
		status = 'Seller-accepting purchase request…';
		const res = await sidecarCall('ownership_seller_accept', {
			request_id: id,
			file_id: r.file_id,
			buyer_address: buyerOf(r),
			asking_price: price
		});
		busy = false;
		status =
			res.ok === false
				? String(res.error)
				: `Approved · tx ${String(res.tx_hash || '').slice(0, 12)}…`;
		await refresh();
	}

	async function rejectIncoming(r: OwnershipReq) {
		busy = true;
		status = 'Rejecting…';
		const res = await sidecarCall('ownership_reject', {
			request_id: reqId(r),
			file_id: r.file_id,
			message: 'Rejected by recipient'
		});
		busy = false;
		status = res.ok === false ? String(res.error) : 'Rejected';
		await refresh();
	}

	async function cancelOutgoing(r: OwnershipReq) {
		busy = true;
		status = 'Cancelling offer…';
		const res = await sidecarCall('ownership_cancel', {
			request_id: reqId(r),
			file_id: r.file_id
		});
		busy = false;
		status = res.ok === false ? String(res.error) : 'Cancelled';
		await refresh();
	}
</script>

<h1>Files</h1>
<p class="lead">
	Digital-asset storage: AES-256-GCM encryption, chunks on BeezStorage, guardian DAM, and on-chain
	<code>upload</code>. Transfer ownership with ECDH-wrapped keys (buyer decrypts after accept). Ask →
	Index is separate (RAG embeddings only).
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
				<button class="ghost" onclick={() => download(String(u.file_id))} disabled={busy}>Download</button>
				<button class="ghost" onclick={() => startTransfer(String(u.file_id))} disabled={busy}
					>Transfer</button
				>
			</li>
		{/each}
	</ul>
	{#if transferFileId}
		<div class="transfer">
			<strong>Offer ownership</strong>
			<p class="meta">File {transferFileId.slice(0, 12)}… · buyer must have a known pubkey on Chain.</p>
			<input type="text" bind:value={transferTo} placeholder="Buyer bez… address" style="width:100%" />
			<div class="row" style="margin-top:0.5rem">
				<label class="meta">Price (BZT)
					<input type="number" bind:value={transferPrice} min="0" step="0.1" style="width:6rem" />
				</label>
				<input type="text" bind:value={transferMsg} placeholder="Optional message" style="flex:1" />
			</div>
			<div class="row" style="margin-top:0.5rem">
				<button class="primary" onclick={submitTransfer} disabled={busy || !transferTo.trim()}
					>Send offer</button
				>
				<button class="ghost" onclick={() => (transferFileId = '')}>Cancel</button>
			</div>
		</div>
	{/if}
</div>

<div class="card" style="margin-top:1rem;max-width:none">
	<strong>Ownership notifications</strong>
	<p class="meta">Incoming offers (you buy) and outgoing offers / purchase requests (you sell).</p>
	{#if incoming.length === 0 && outgoing.length === 0}
		<p class="meta">No pending ownership requests.</p>
	{/if}
	{#if incoming.length}
		<p class="meta" style="margin-top:0.5rem"><strong>Incoming</strong></p>
		<ul class="node-list">
			{#each incoming as r}
				<li>
					<strong>{String(r.file_name || r.file_id)}</strong>
					<span class="caps"
						>from {sellerOf(r).slice(0, 12)}… · {priceNum(r)} BZT</span
					>
					<button class="primary" onclick={() => acceptIncoming(r)} disabled={busy}>Accept</button>
					<button class="ghost" onclick={() => rejectIncoming(r)} disabled={busy}>Reject</button>
				</li>
			{/each}
		</ul>
	{/if}
	{#if outgoing.length}
		<p class="meta" style="margin-top:0.5rem"><strong>Outgoing</strong></p>
		<ul class="node-list">
			{#each outgoing as r}
				<li>
					<strong>{String(r.file_name || r.file_id)}</strong>
					<span class="caps"
						>to {buyerOf(r).slice(0, 12)}… · {priceNum(r)} BZT · {r.status || 'pending'}</span
					>
					<button class="ghost" onclick={() => sellerAcceptOutgoing(r)} disabled={busy}
						>Approve as seller</button
					>
					<button class="ghost" onclick={() => cancelOutgoing(r)} disabled={busy}>Cancel</button>
				</li>
			{/each}
		</ul>
	{/if}
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
		font-size: 0.88rem;
	}
	.transfer {
		margin-top: 0.75rem;
		padding-top: 0.75rem;
		border-top: 1px solid var(--border);
	}
</style>
