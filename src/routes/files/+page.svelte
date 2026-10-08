<script lang="ts">
	import { sidecarCall } from '#lib';
	import { open } from '@tauri-apps/plugin-dialog';

	type MyFile = {
		file_id: string;
		file_name?: string;
		file_size?: number;
		num_chunks?: number;
		visibility?: string;
		price?: number | string;
		marketplace_price?: number | string;
		storage_duration?: number;
		tx_hash?: string;
		block_height?: number;
		timestamp?: string;
		guardian_dam_id?: string;
		chunk_locations?: Record<string, string[]>;
		backup_chunk_locations?: Record<string, string[]>;
		tags?: string[];
		status?: string;
		transfer_locked?: boolean;
		acquired_via?: string;
		original_uploader?: string;
	};

	type MarketAsset = {
		file_id: string;
		file_name?: string;
		extension?: string;
		file_size?: number;
		marketplace_price?: number;
		owner_address?: string;
		tags?: string[];
		created_at?: string;
	};

	type OwnershipReq = {
		request_id: string;
		file_id: string;
		file_name?: string;
		asking_price?: string | number;
		current_owner_address?: string;
		new_owner_address?: string;
		created_at?: string;
		message?: string;
	};

	type PendingTx = { type?: string; file_id?: string; tx_hash?: string };

	type Tab = 'store' | 'mine' | 'market' | 'transfers';

	// Mirrors BeezChain fee_config.TRANSACTION_FEES.
	const FEE = { upload: 0.1, request: 0.05, accept: 0.05, reject: 0.01, cancel: 0.01, listing: 0.01 };
	const YEARS = [3, 5, 7, 10];
	const NODE_COUNTS = [1, 3, 6];

	const PENDING_LABEL: Record<string, string> = {
		upload: 'Upload waiting for the next block',
		update_digital_asset_price: 'Price change waiting for the next block',
		update_digital_asset_visibility: 'Marketplace change waiting for the next block',
		ownership_request: 'Transfer request waiting for the next block',
		ownership_accept: 'Transfer approval waiting for the next block',
		ownership_reject: 'Decline waiting for the next block',
		ownership_cancel: 'Withdrawal waiting for the next block'
	};

	let tab = $state<Tab>('store');
	let address = $state('');
	let balance = $state<number | null>(null);
	let pendingTxs = $state<PendingTx[]>([]);
	let busy = $state(false);
	let status = $state('');

	let path = $state('');
	let visibility = $state<'private' | 'public'>('private');
	let duration = $state(5);
	let nodeCount = $state(3);
	let price = $state(0);
	let tags = $state('');
	let estimate = $state<Record<string, unknown> | null>(null);

	let files = $state<MyFile[]>([]);
	let filesError = $state('');
	let filter = $state('');
	let details = $state<string | null>(null);
	let listingEdit = $state<{ fileId: string; visibility: string; price: number } | null>(null);
	let sendEdit = $state<{ fileId: string; to: string; price: number; message: string } | null>(null);

	let marketQuery = $state('');
	let market = $state<MarketAsset[]>([]);
	let marketTotal = $state<number | null>(null);
	let marketError = $state('');

	let incoming = $state<OwnershipReq[]>([]);
	let outgoing = $state<OwnershipReq[]>([]);

	const fileName = $derived(path.split(/[\\/]/).pop() || '');
	const shown = $derived(
		files.filter((f) => (f.file_name || f.file_id).toLowerCase().includes(filter.trim().toLowerCase()))
	);
	const listedCount = $derived(files.filter((f) => f.visibility === 'public').length);
	const totalBytes = $derived(files.reduce((s, f) => s + Number(f.file_size || 0), 0));
	const pendingByFile = $derived.by(() => {
		const m = new Map<string, string[]>();
		for (const t of pendingTxs) {
			if (!t.file_id || !t.type || !PENDING_LABEL[t.type]) continue;
			m.set(t.file_id, [...(m.get(t.file_id) || []), PENDING_LABEL[t.type]]);
		}
		return m;
	});
	const pendingOwnership = $derived(pendingTxs.filter((t) => String(t.type || '').startsWith('ownership_')));
	const storageCost = $derived(Number(estimate?.estimated_cost || 0));
	const uploadTotal = $derived(storageCost + FEE.upload);

	function bzt(n: number | string | undefined | null): string {
		const v = Number(String(n ?? 0).replace(/BZT/gi, '').trim()) || 0;
		return `${Number.isInteger(v) ? v : v.toFixed(v < 1 ? 4 : 2).replace(/0+$/, '').replace(/\.$/, '')} BZT`;
	}

	function num(n: number | string | undefined | null): number {
		return Number(String(n ?? 0).replace(/BZT/gi, '').trim()) || 0;
	}

	function size(bytes: number | undefined): string {
		const b = Number(bytes || 0);
		if (b < 1024) return `${b} B`;
		if (b < 1024 ** 2) return `${(b / 1024).toFixed(1)} KB`;
		if (b < 1024 ** 3) return `${(b / 1024 ** 2).toFixed(1)} MB`;
		return `${(b / 1024 ** 3).toFixed(2)} GB`;
	}

	function short(addr: string | undefined): string {
		const a = String(addr || '');
		return a.length > 16 ? `${a.slice(0, 10)}…${a.slice(-4)}` : a;
	}

	function errText(e: unknown): string {
		let v = e;
		for (let i = 0; i < 4 && v && typeof v === 'object'; i++) {
			const o = v as Record<string, unknown>;
			v = o.body ?? o.error ?? o.message ?? JSON.stringify(o);
		}
		return String(v ?? 'Unknown error');
	}

	function parseTags(s: string): string[] {
		return s
			.split(',')
			.map((t) => t.trim())
			.filter(Boolean);
	}

	function iAmSeller(r: OwnershipReq): boolean {
		return r.current_owner_address === address;
	}

	async function refreshWallet() {
		const ledger = await sidecarCall('wallet_ledger');
		address = String(ledger.address || '');
		const n = Number(ledger.balance);
		balance = ledger.ok !== false && ledger.balance != null && !Number.isNaN(n) ? n : null;
		pendingTxs = Array.isArray(ledger.pending) ? (ledger.pending as PendingTx[]) : [];
	}

	async function loadFiles() {
		const r = await sidecarCall('asset_list');
		filesError = r.ok === false ? errText(r.error) : '';
		files = (r.uploads as MyFile[]) || [];
	}

	async function loadTransfers() {
		const p = await sidecarCall('ownership_pending');
		if (p.ok === false) return;
		incoming = (p.incoming as OwnershipReq[]) || [];
		outgoing = (p.outgoing as OwnershipReq[]) || [];
	}

	async function searchMarket() {
		const r = await sidecarCall('asset_marketplace', { query: marketQuery, limit: 100 });
		marketError = r.ok === false ? errText(r.error) : '';
		market = (r.assets as MarketAsset[]) || [];
		marketTotal = r.total == null ? null : Number(r.total);
	}

	async function refreshAll() {
		await refreshWallet();
		await Promise.all([loadFiles(), loadTransfers(), searchMarket()]);
	}

	let loaded = $state(false);
	$effect(() => {
		if (loaded) return;
		loaded = true;
		refreshAll();
	});

	$effect(() => {
		const args = { path, duration, node_count: nodeCount };
		if (!args.path) {
			estimate = null;
			return;
		}
		sidecarCall('asset_upload_estimate', args).then((r) => {
			if (args.path === path) estimate = r;
		});
	});

	async function browse() {
		try {
			const picked = await open({ multiple: false });
			if (typeof picked === 'string') path = picked;
		} catch (err) {
			status = String(err);
		}
	}

	async function upload() {
		if (!path || busy || !estimate?.ok) return;
		await refreshWallet();
		if (balance != null && balance < uploadTotal) {
			status = `Not enough BZT: storing this file costs about ${bzt(uploadTotal)}, your wallet has ${bzt(balance)}.`;
			return;
		}
		if (
			!confirm(
				`Store “${fileName}” for ${duration} years?\n\n` +
					`Storage: about ${bzt(storageCost)} (paid up front into escrow)\nNetwork fee: ${bzt(FEE.upload)}\n\n` +
					(visibility === 'public'
						? `It will be listed on the Marketplace at ${bzt(price)}. The content stays encrypted.`
						: 'It stays private: only your wallet can see and decrypt it.')
			)
		)
			return;
		busy = true;
		status = 'Encrypting on this device, sending chunks to Storage nodes, then registering the file on chain… Large files take a while.';
		const r = await sidecarCall('asset_upload', {
			path,
			visibility,
			duration,
			node_count: nodeCount,
			price: visibility === 'public' ? Number(price) : 0,
			tags: parseTags(tags)
		});
		busy = false;
		if (r.ok === false) {
			status = errText(r.error);
			return;
		}
		status = `Stored “${r.file_name}” in ${r.chunks} encrypted chunk(s) for ${bzt(Number(r.cost))}. It shows as confirmed after the next block (~5 min).`;
		path = '';
		tags = '';
		price = 0;
		tab = 'mine';
		await Promise.all([loadFiles(), refreshWallet()]);
	}

	async function download(f: MyFile) {
		try {
			const dir = await open({ directory: true, multiple: false });
			if (typeof dir !== 'string') return;
			busy = true;
			status = `Fetching “${f.file_name}” from Storage nodes and decrypting it…`;
			const r = await sidecarCall('asset_download', { file_id: f.file_id, dest_dir: dir });
			status = r.ok === false ? errText(r.error) : `Saved to ${r.path}`;
		} catch (err) {
			status = String(err);
		} finally {
			busy = false;
		}
	}

	function openListing(f: MyFile) {
		sendEdit = null;
		listingEdit = { fileId: f.file_id, visibility: f.visibility || 'private', price: num(f.marketplace_price ?? f.price) };
	}

	function openSend(f: MyFile) {
		listingEdit = null;
		sendEdit = { fileId: f.file_id, to: '', price: 0, message: '' };
	}

	async function saveListing(f: MyFile) {
		if (!listingEdit || busy) return;
		const oldPrice = num(f.marketplace_price ?? f.price);
		const params: Record<string, unknown> = { file_id: f.file_id, old_price: oldPrice };
		if (listingEdit.visibility !== (f.visibility || 'private')) params.visibility = listingEdit.visibility;
		if (listingEdit.visibility === 'public' && Number(listingEdit.price) !== oldPrice) params.price = Number(listingEdit.price);
		const changes = Number('visibility' in params) + Number('price' in params);
		if (!changes) {
			listingEdit = null;
			return;
		}
		busy = true;
		const r = await sidecarCall('asset_set_listing', params);
		busy = false;
		if (r.ok === false) {
			status = errText(r.error);
			return;
		}
		status =
			listingEdit.visibility === 'public'
				? `“${f.file_name}” will be on the Marketplace at ${bzt(listingEdit.price)} after the next block (~5 min).`
				: `“${f.file_name}” will be private again after the next block (~5 min).`;
		listingEdit = null;
		await refreshWallet();
	}

	async function sendOffer(f: MyFile) {
		if (!sendEdit || busy) return;
		const to = sendEdit.to.trim();
		if (!to.startsWith('bez')) {
			status = 'Enter the recipient wallet address (it starts with “bez”).';
			return;
		}
		if (
			!confirm(
				`Offer “${f.file_name}” to ${short(to)} for ${bzt(sendEdit.price)}?\n\n` +
					`They must accept${Number(sendEdit.price) > 0 ? ' and pay' : ''} before ownership moves. Network fee: ${bzt(FEE.request)}.`
			)
		)
			return;
		busy = true;
		status = 'Wrapping your file key for the recipient and sending the offer…';
		const r = await sidecarCall('ownership_transfer', {
			file_id: f.file_id,
			new_owner: to,
			asking_price: Number(sendEdit.price),
			message: sendEdit.message
		});
		busy = false;
		if (r.ok === false) {
			status = errText(r.error);
			return;
		}
		status = `Offer sent. It appears under Transfers after the next block (~5 min).`;
		sendEdit = null;
		await refreshWallet();
	}

	async function requestPurchase(a: MarketAsset) {
		if (busy) return;
		const p = Number(a.marketplace_price || 0);
		await refreshWallet();
		const total = p + FEE.request + FEE.accept;
		if (balance != null && balance < total) {
			status = `Not enough BZT: buying costs ${bzt(p)} plus ${bzt(FEE.request + FEE.accept)} in network fees, your wallet has ${bzt(balance)}.`;
			return;
		}
		if (
			!confirm(
				`Ask to buy “${a.file_name}” for ${bzt(p)}?\n\n` +
					`Now: ${bzt(FEE.request)} network fee for the request.\n` +
					`When the owner approves: ${bzt(p)} goes to the owner, plus a ${bzt(FEE.accept)} fee, and the file becomes yours.`
			)
		)
			return;
		busy = true;
		status = 'Sending your purchase request…';
		const r = await sidecarCall('asset_purchase_request', { file_id: a.file_id });
		busy = false;
		if (r.ok === false) {
			status = errText(r.error);
			return;
		}
		status = `Request sent to ${short(String(r.seller))}. Track it under Transfers; it appears after the next block (~5 min).`;
		await refreshWallet();
	}

	async function act(
		r: OwnershipReq,
		method: 'ownership_accept' | 'ownership_seller_accept' | 'ownership_reject' | 'ownership_cancel',
		question: string,
		done: string
	) {
		if (busy || !confirm(question)) return;
		busy = true;
		status = 'Submitting…';
		const res = await sidecarCall(method, {
			request_id: r.request_id,
			file_id: r.file_id,
			asking_price: num(r.asking_price),
			buyer_address: r.new_owner_address
		});
		busy = false;
		status = res.ok === false ? errText(res.error) : `${done} It takes effect after the next block (~5 min).`;
		await refreshWallet();
	}
</script>

<h1>Files</h1>
<p class="lead">
	Store files on the Beez network so only your wallet can read them, and buy or sell them with BZT.
	Storage nodes keep encrypted pieces they cannot read; the blockchain records who owns each file.
</p>

<div class="steps">
	<div class="step">
		<div class="step-num">1</div>
		<div>
			<strong>Store</strong>
			<p>
				The file is encrypted on this device (AES-256-GCM, key derived from your wallet), split into
				1 MB chunks and stored on Storage nodes. A DAM guardian keeps checking they still hold them.
			</p>
		</div>
	</div>
	<div class="step">
		<div class="step-num">2</div>
		<div>
			<strong>Manage</strong>
			<p>Download and decrypt at any time. Keep a file private, or list it on the Marketplace with an asking price.</p>
		</div>
	</div>
	<div class="step">
		<div class="step-num">3</div>
		<div>
			<strong>Trade</strong>
			<p>
				A buyer requests, the owner approves. The chain moves the BZT and gives the buyer a copy of the
				key that only their wallet can open.
			</p>
		</div>
	</div>
</div>

<div class="tabs" role="tablist">
	<button class:active={tab === 'store'} onclick={() => (tab = 'store')}>Store a file</button>
	<button class:active={tab === 'mine'} onclick={() => (tab = 'mine')}>
		My files{#if files.length} ({files.length}){/if}
	</button>
	<button class:active={tab === 'market'} onclick={() => (tab = 'market')}>Marketplace</button>
	<button class:active={tab === 'transfers'} onclick={() => (tab = 'transfers')}>
		Transfers{#if incoming.length}<span class="badge">{incoming.length}</span>{/if}
	</button>
</div>

{#if status}<p class="callout">{status}</p>{/if}

{#if tab === 'store'}
	<div class="split">
		<div class="card stack">
			<h2>1 · Choose a file</h2>
			<div class="row">
				<input type="text" class="grow" bind:value={path} placeholder="Path of the file to store" />
				<button class="ghost" onclick={browse} disabled={busy}>Browse…</button>
			</div>
			{#if estimate?.ok}
				<p class="meta" style="margin:0">
					<strong>{fileName}</strong> · {size(Number(estimate.file_size))} · {estimate.chunks} encrypted chunk(s)
				</p>
			{:else if estimate?.ok === false}
				<p class="meta error" style="margin:0">{errText(estimate.error)}</p>
			{:else}
				<p class="meta" style="margin:0">Any file up to 500 MB. It never leaves this device unencrypted.</p>
			{/if}

			<h2>2 · Storage plan</h2>
			<div class="field">
				<span>How long to keep it</span>
				<div class="row">
					{#each YEARS as y}
						<button class={duration === y ? 'primary' : 'ghost'} onclick={() => (duration = y)}>{y} years</button>
					{/each}
				</div>
				<p class="meta" style="margin:0">
					You pay the whole period up front. The BZT sits in escrow and is released to the Storage nodes
					over time, only while the DAM guardian confirms they still hold your chunks.
				</p>
			</div>
			<div class="field">
				<span>Storage nodes</span>
				<div class="row">
					{#each NODE_COUNTS as n}
						<button class={nodeCount === n ? 'primary' : 'ghost'} onclick={() => (nodeCount = n)}>
							{n} node{n > 1 ? 's' : ''}
						</button>
					{/each}
				</div>
				<p class="meta" style="margin:0">
					Chunks are spread across this many nodes and each chunk also gets backup copies elsewhere. More
					nodes means more resilience at the same price per chunk.
				</p>
			</div>
			<div class="field">
				<span>Who can see it</span>
				<div class="choices">
					<label class="choice" class:active={visibility === 'private'}>
						<input type="radio" bind:group={visibility} value="private" />
						<div>
							<strong>Private</strong>
							<p>Only your wallet can see and decrypt it.</p>
						</div>
					</label>
					<label class="choice" class:active={visibility === 'public'}>
						<input type="radio" bind:group={visibility} value="public" />
						<div>
							<strong>On the Marketplace</strong>
							<p>Others see name, size, tags and price, and can ask to buy. The content stays encrypted.</p>
						</div>
					</label>
				</div>
			</div>
			{#if visibility === 'public'}
				<div class="row">
					<label class="field grow">
						<span>Asking price (BZT, paid to you when you approve a sale)</span>
						<input type="number" bind:value={price} min="0" step="0.1" />
					</label>
					<label class="field grow">
						<span>Tags (comma separated, help buyers find it)</span>
						<input type="text" bind:value={tags} placeholder="dataset, legal, report" />
					</label>
				</div>
			{/if}
		</div>

		<div class="card stack">
			<h2>3 · Cost and confirm</h2>
			{#if estimate?.ok}
				<dl class="kv">
					<dt>Encrypted chunks</dt>
					<dd>{estimate.chunks} × 1 MB max</dd>
					<dt>Price per chunk per year</dt>
					<dd>≈ {bzt(Number(estimate.price_per_chunk))}</dd>
					<dt>Storage for {duration} years</dt>
					<dd>≈ {bzt(storageCost)}</dd>
					<dt>Network fee</dt>
					<dd>{bzt(FEE.upload)}</dd>
					<dt>Total</dt>
					<dd class="total">≈ {bzt(uploadTotal)}</dd>
					<dt>Your balance</dt>
					<dd class:error={balance != null && balance < uploadTotal}>{balance == null ? '—' : bzt(balance)}</dd>
					<dt>Storage nodes</dt>
					<dd>
						{#each (estimate.nodes as Record<string, unknown>[]) || [] as n, i}{i ? ', ' : ''}{String(n.node_id)}{/each}
					</dd>
					<dt>DAM guardian</dt>
					<dd>{String(estimate.guardian_dam_id || 'none available')}</dd>
				</dl>
				<p class="meta" style="margin:0">
					The exact amount depends on which node accepts each chunk; it is shown after the upload.
				</p>
				<div>
					<button class="primary" onclick={upload} disabled={busy || (balance != null && balance < uploadTotal)}>
						Encrypt and store
					</button>
				</div>
			{:else}
				<p class="lead">Choose a file to see the cost, the Storage nodes that will hold it and its DAM guardian.</p>
			{/if}
		</div>
	</div>
{:else if tab === 'mine'}
	<div class="stats" style="margin-bottom:1rem">
		<div class="stat"><div class="value">{files.length}</div><div class="label">Files you own</div></div>
		<div class="stat"><div class="value">{size(totalBytes)}</div><div class="label">Stored</div></div>
		<div class="stat"><div class="value">{listedCount}</div><div class="label">On the Marketplace</div></div>
		<div class="stat"><div class="value">{balance == null ? '—' : bzt(balance)}</div><div class="label">Wallet balance</div></div>
	</div>
	<div class="row" style="margin-bottom:1rem">
		<input type="search" class="grow" bind:value={filter} placeholder="Search your files by name" />
		<button class="ghost" onclick={() => Promise.all([loadFiles(), refreshWallet()])} disabled={busy}>Refresh</button>
	</div>
	{#if filesError}<p class="meta error">Could not load your files: {filesError}</p>{/if}
	{#if files.length === 0 && !filesError}
		<p class="lead">
			No files yet. <button class="ghost" onclick={() => (tab = 'store')}>Store your first file</button>
		</p>
	{:else if shown.length === 0}
		<p class="meta">No file name matches “{filter}”.</p>
	{/if}

	<div class="stack">
		{#each shown as f (f.file_id)}
			{@const confirmed = f.status !== 'pending'}
			{@const locked = Boolean(f.transfer_locked)}
			<div class="card stack">
				<div class="row" style="justify-content:space-between">
					<div class="row">
						<h2 style="margin:0">{f.file_name || f.file_id}</h2>
						<span class="chip {confirmed ? 'ok' : 'warn'}">{confirmed ? 'Confirmed' : 'Waiting for block'}</span>
						{#if f.visibility === 'public'}
							<span class="chip">On Marketplace · {bzt(f.marketplace_price ?? f.price)}</span>
						{:else}
							<span class="chip muted">Private</span>
						{/if}
						{#if f.acquired_via}<span class="chip muted">Received from {short(f.original_uploader)}</span>{/if}
						{#if locked}<span class="chip warn">Transfer pending</span>{/if}
					</div>
					<div class="row">
						<button class="primary" onclick={() => download(f)} disabled={busy || !confirmed}>Download</button>
						<button class="ghost" onclick={() => openListing(f)} disabled={busy || !confirmed || locked}>Marketplace…</button>
						<button class="ghost" onclick={() => openSend(f)} disabled={busy || !confirmed || locked}>Send to a wallet…</button>
						<button class="ghost" onclick={() => (details = details === f.file_id ? null : f.file_id)}>
							{details === f.file_id ? 'Hide details' : 'Details'}
						</button>
					</div>
				</div>
				<p class="meta" style="margin:0">
					{size(f.file_size)} · {f.num_chunks ?? '?'} chunk(s) · stored for {f.storage_duration ?? '?'} years ·
					{String(f.timestamp || '').slice(0, 16) || 'just now'}
					{#if f.tags?.length}· {f.tags.join(', ')}{/if}
				</p>
				{#each pendingByFile.get(f.file_id) || [] as p}<p class="meta" style="margin:0">⏳ {p}</p>{/each}

				{#if listingEdit?.fileId === f.file_id}
					<div class="stack" style="border-top:1px solid var(--border); padding-top:0.75rem">
						<div class="choices">
							<label class="choice" class:active={listingEdit.visibility === 'private'}>
								<input type="radio" bind:group={listingEdit.visibility} value="private" />
								<div><strong>Private</strong><p>Hidden from the Marketplace.</p></div>
							</label>
							<label class="choice" class:active={listingEdit.visibility === 'public'}>
								<input type="radio" bind:group={listingEdit.visibility} value="public" />
								<div><strong>On the Marketplace</strong><p>Buyers can ask to buy it at your price.</p></div>
							</label>
						</div>
						{#if listingEdit.visibility === 'public'}
							<label class="field" style="max-width:20rem">
								<span>Asking price (BZT)</span>
								<input type="number" bind:value={listingEdit.price} min="0" step="0.1" />
							</label>
						{/if}
						<p class="meta" style="margin:0">
							Each change is an on-chain transaction ({bzt(FEE.listing)} fee) and applies after the next block.
							You still approve every sale yourself.
						</p>
						<div class="row">
							<button class="primary" onclick={() => saveListing(f)} disabled={busy}>Save</button>
							<button class="ghost" onclick={() => (listingEdit = null)}>Cancel</button>
						</div>
					</div>
				{/if}

				{#if sendEdit?.fileId === f.file_id}
					<div class="stack" style="border-top:1px solid var(--border); padding-top:0.75rem">
						<label class="field">
							<span>Recipient wallet address</span>
							<input type="text" bind:value={sendEdit.to} placeholder="bez…" />
						</label>
						<div class="row">
							<label class="field" style="width:12rem">
								<span>Price (BZT, 0 = gift)</span>
								<input type="number" bind:value={sendEdit.price} min="0" step="0.1" />
							</label>
							<label class="field grow">
								<span>Message (optional)</span>
								<input type="text" bind:value={sendEdit.message} />
							</label>
						</div>
						<p class="meta" style="margin:0">
							The recipient must accept{Number(sendEdit.price) > 0 ? ' and pay' : ''}. Your file key is
							re-encrypted for their wallet, so only they can open it. Their wallet must have made at
							least one transaction so its public key is on chain. Network fee {bzt(FEE.request)}.
						</p>
						<div class="row">
							<button class="primary" onclick={() => sendOffer(f)} disabled={busy || !sendEdit.to.trim()}>Send offer</button>
							<button class="ghost" onclick={() => (sendEdit = null)}>Cancel</button>
						</div>
					</div>
				{/if}

				{#if details === f.file_id}
					<dl class="kv" style="border-top:1px solid var(--border); padding-top:0.75rem">
						<dt>File id</dt><dd><code>{f.file_id}</code></dd>
						<dt>Upload transaction</dt><dd><code>{f.tx_hash || '—'}</code>{#if f.block_height} · block {f.block_height}{/if}</dd>
						<dt>Encryption</dt><dd>AES-256-GCM, key derived from {f.acquired_via ? "the seller's key, re-encrypted for your wallet" : 'your wallet'}</dd>
						<dt>DAM guardian</dt><dd>{f.guardian_dam_id || '—'}</dd>
						{#each Object.entries(f.chunk_locations || {}) as [chunk, nodes]}
							<dt>Chunk {chunk.split('_chunk_').pop()}</dt>
							<dd>
								{nodes.join(', ')}
								{#if f.backup_chunk_locations?.[chunk]?.length}
									<span class="meta">· backups {f.backup_chunk_locations[chunk].join(', ')}</span>
								{/if}
							</dd>
						{/each}
					</dl>
				{/if}
			</div>
		{/each}
	</div>
{:else if tab === 'market'}
	<p class="meta">
		Files other wallets have listed. You see the name, size, tags and asking price; the content stays
		encrypted until the owner approves your request and the payment goes through.
	</p>
	<div class="row" style="margin-bottom:1rem">
		<input
			type="search"
			class="grow"
			bind:value={marketQuery}
			placeholder="Search by file name"
			onkeydown={(e) => e.key === 'Enter' && searchMarket()}
		/>
		<button class="primary" onclick={searchMarket} disabled={busy}>Search</button>
	</div>
	{#if marketError}<p class="meta error">Could not load the Marketplace: {marketError}</p>{/if}
	{#if market.length === 0 && !marketError}
		<p class="meta">Nothing listed{marketQuery ? ` matches “${marketQuery}”` : ' yet'}.</p>
	{:else}
		<p class="meta">{marketTotal ?? market.length} file(s) listed{marketQuery ? ` matching “${marketQuery}”` : ''}.</p>
	{/if}
	<div class="listings">
		{#each market as a (a.file_id)}
			{@const mine = a.owner_address === address}
			<div class="listing" style="cursor:default">
				<div class="row" style="justify-content:space-between">
					<strong>{a.file_name}{a.extension && !String(a.file_name).endsWith(a.extension) ? a.extension : ''}</strong>
					{#if mine}<span class="chip muted">Yours</span>{/if}
				</div>
				<div class="row">
					<span class="chip">{Number(a.marketplace_price || 0) > 0 ? bzt(a.marketplace_price) : 'Free'}</span>
					<span class="chip muted">{size(a.file_size)}</span>
					{#each a.tags || [] as t}<span class="chip muted">{t}</span>{/each}
				</div>
				<span class="meta" style="margin:0">
					Owner {short(a.owner_address)} · listed {String(a.created_at || '').slice(0, 10)}
				</span>
				{#if !mine}
					<div>
						<button class="primary" onclick={() => requestPurchase(a)} disabled={busy}>Ask to buy</button>
					</div>
				{/if}
			</div>
		{/each}
	</div>
{:else}
	<p class="meta">
		A transfer needs both sides: one wallet proposes (an owner's offer or a buyer's request), the other
		approves or declines. On approval the chain moves the BZT and the file's ownership together. New
		requests appear here after the next block (~5 min).
	</p>
	{#if pendingOwnership.length}
		<p class="callout">
			{pendingOwnership.length} transfer transaction(s) of yours are waiting for the next block.
		</p>
	{/if}

	<h2>Waiting for you ({incoming.length})</h2>
	{#if incoming.length === 0}<p class="meta">Nothing needs your decision.</p>{/if}
	<div class="stack">
		{#each incoming as r (r.request_id)}
			{@const p = num(r.asking_price)}
			<div class="card row" style="justify-content:space-between">
				<div class="stack" style="gap:0.25rem">
					{#if iAmSeller(r)}
						<strong>{short(r.new_owner_address)} wants to buy “{r.file_name}” for {bzt(p)}</strong>
						<span class="meta" style="margin:0">
							Approving gives them a copy of your file key and moves ownership to them; you receive {bzt(p)}.
						</span>
					{:else}
						<strong>{short(r.current_owner_address)} offers you “{r.file_name}” for {bzt(p)}</strong>
						<span class="meta" style="margin:0">
							Accepting pays {bzt(p)} + {bzt(FEE.accept)} fee and makes the file yours to download.
						</span>
					{/if}
					{#if r.message}<span class="meta" style="margin:0">“{r.message}”</span>{/if}
				</div>
				<div class="row">
					{#if iAmSeller(r)}
						<button class="primary" disabled={busy}
							onclick={() => act(r, 'ownership_seller_accept', `Sell “${r.file_name}” to ${short(r.new_owner_address)} for ${bzt(p)}?`, 'Sale approved.')}
						>Approve sale</button>
						<button class="ghost" disabled={busy}
							onclick={() => act(r, 'ownership_cancel', `Decline the request for “${r.file_name}”? Fee ${bzt(FEE.cancel)}.`, 'Request declined.')}
						>Decline</button>
					{:else}
						<button class="primary" disabled={busy || (balance != null && balance < p + FEE.accept)}
							onclick={() => act(r, 'ownership_accept', `Pay ${bzt(p)} + ${bzt(FEE.accept)} fee and take ownership of “${r.file_name}”?`, 'Accepted.')}
						>Accept · {bzt(p)}</button>
						<button class="ghost" disabled={busy}
							onclick={() => act(r, 'ownership_reject', `Decline the offer for “${r.file_name}”? Fee ${bzt(FEE.reject)}.`, 'Offer declined.')}
						>Decline</button>
					{/if}
				</div>
			</div>
		{/each}
	</div>

	<h2 style="margin-top:1.5rem">Waiting for the other side ({outgoing.length})</h2>
	{#if outgoing.length === 0}<p class="meta">You have no open offers or requests.</p>{/if}
	<div class="stack">
		{#each outgoing as r (r.request_id)}
			{@const p = num(r.asking_price)}
			<div class="card row" style="justify-content:space-between">
				<div class="stack" style="gap:0.25rem">
					{#if iAmSeller(r)}
						<strong>You offered “{r.file_name}” to {short(r.new_owner_address)} for {bzt(p)}</strong>
						<span class="meta" style="margin:0">They have to accept. The file stays yours until they do.</span>
					{:else}
						<strong>You asked to buy “{r.file_name}” for {bzt(p)}</strong>
						<span class="meta" style="margin:0">
							Waiting for {short(r.current_owner_address)} to approve. Nothing is paid until then.
						</span>
					{/if}
				</div>
				<button class="ghost" disabled={busy}
					onclick={() =>
						iAmSeller(r)
							? act(r, 'ownership_cancel', `Withdraw your offer for “${r.file_name}”? Fee ${bzt(FEE.cancel)}.`, 'Offer withdrawn.')
							: act(r, 'ownership_reject', `Withdraw your request for “${r.file_name}”? Fee ${bzt(FEE.reject)}.`, 'Request withdrawn.')}
				>Withdraw</button>
			</div>
		{/each}
	</div>
{/if}
