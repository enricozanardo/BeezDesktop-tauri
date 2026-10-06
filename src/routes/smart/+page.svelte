<script lang="ts">
	import { sidecarCall } from '#lib';

	type SmartNode = Record<string, unknown> & {
		node_id?: string;
		ip?: string;
		capabilities?: string[];
		price_per_query?: number;
		suitability?: number;
		label?: string;
		gguf_present?: boolean;
		running?: boolean;
		llm_backend?: string;
	};

	type ChatMsg = {
		role: 'user' | 'assistant';
		content: string;
		sources?: unknown[];
		cost?: number;
		verification?: Record<string, unknown> | null;
		tx_hash?: string;
		local?: boolean;
		error?: string;
	};

	let nodes = $state<SmartNode[]>([]);
	let selected = $state<SmartNode | null>(null);
	let needed = $state<string[]>([]);
	let messages = $state<ChatMsg[]>([]);
	let draft = $state('');
	let attachPath = $state('');
	let fileIds = $state<string[]>([]);
	let busy = $state(false);
	let status = $state('');
	let discoverError = $state('');
	let threadId = $state<string | undefined>(undefined);
	let minicpm = $state<Record<string, unknown> | null>(null);
	let poll: ReturnType<typeof setInterval> | undefined;

	function capList(n: SmartNode): string {
		const caps = n.capabilities;
		if (Array.isArray(caps)) return caps.join(', ');
		return String(caps || 'generic');
	}

	async function refreshNodes(prompt = '') {
		discoverError = '';
		const ranked = (await sidecarCall('rank_smart_nodes', {
			prompt,
			attachments: attachPath ? [attachPath] : []
		})) as Record<string, unknown>;
		needed = (ranked.needed as string[]) || [];
		nodes = (ranked.nodes as SmartNode[]) || [];
		const errs = ranked.errors as unknown[] | undefined;
		if ((!nodes || nodes.length === 0) && errs?.length) {
			discoverError = JSON.stringify(errs);
		}
		if (!selected && nodes.length) selected = nodes[0];
		if (selected) {
			const match = nodes.find((n) => n.node_id === selected?.node_id);
			if (match) selected = match;
		}
		minicpm = await sidecarCall('minicpm_status');
	}

	function downloadInfo(): { active?: boolean; bytes?: number; total?: number; error?: string } {
		const d = minicpm?.download as Record<string, unknown> | undefined;
		if (!d) return {};
		return {
			active: Boolean(d.active),
			bytes: Number(d.bytes || 0),
			total: d.total == null ? undefined : Number(d.total),
			error: d.error ? String(d.error) : undefined
		};
	}

	let loaded = $state(false);
	$effect(() => {
		if (loaded) return;
		loaded = true;
		refreshNodes();
	});

	function pick(n: SmartNode) {
		selected = n;
	}

	async function send() {
		const text = draft.trim();
		if (!text || busy) return;
		busy = true;
		status = '';
		const user: ChatMsg = { role: 'user', content: text };
		messages = [...messages, user];
		draft = '';
		await refreshNodes(text);
		const node = selected || nodes[0];
		if (!node) {
			busy = false;
			messages = [
				...messages,
				{ role: 'assistant', content: 'No Smart node available yet.', error: 'no node' }
			];
			return;
		}
		if (node.node_id !== 'local_minicpm') {
			status = 'Preparing embedding model (first run may download it)…';
			const ready = await sidecarCall('embed_ensure');
			if (ready.ok === false) {
				busy = false;
				messages = [
					...messages,
					{ role: 'assistant', content: String(ready.error), error: String(ready.error) }
				];
				return;
			}
		}
		status = '';
		const payload = {
			node,
			messages: messages.map((m) => ({ role: m.role, content: m.content })),
			file_ids: fileIds,
			thread_id: threadId
		};
		const result = (await sidecarCall('chat', payload)) as Record<string, unknown>;
		busy = false;
		if (result.ok === false) {
			messages = [...messages, { role: 'assistant', content: String(result.error), error: String(result.error) }];
			return;
		}
		if (typeof result.thread_id === 'string') threadId = result.thread_id;
		messages = [
			...messages,
			{
				role: 'assistant',
				content: String(result.answer || ''),
				sources: (result.sources as unknown[]) || [],
				cost: Number(result.cost || 0),
				verification: (result.verification as Record<string, unknown>) || null,
				tx_hash: result.tx_hash as string | undefined,
				local: Boolean(result.local)
			}
		];
	}

	async function indexAttach() {
		if (!attachPath || !selected) return;
		busy = true;
		status = 'Preparing embedding model, then indexing…';
		const ready = await sidecarCall('embed_ensure');
		if (ready.ok === false) {
			busy = false;
			status = String(ready.error);
			return;
		}
		status = 'Indexing file into the selected Smart workspace…';
		const result = (await sidecarCall('index_file', {
			path: attachPath,
			node: selected
		})) as Record<string, unknown>;
		busy = false;
		if (result.ok === false) {
			status = String(result.error);
			return;
		}
		const fid = String(result.file_id || '');
		if (fid) fileIds = [...new Set([...fileIds, fid])];
		status = `Indexed ${fid.slice(0, 8)}… (${JSON.stringify((result.result as Record<string, unknown>)?.chunks_indexed)}) chunks`;
	}

	async function downloadMini() {
		status = 'Starting MiniCPM download in the background…';
		const r = await sidecarCall('minicpm_download');
		status = r.already_present
			? 'Model already on disk.'
			: String(r.message || r.error || 'Downloading…');
		if (poll) clearInterval(poll);
		poll = setInterval(async () => {
			minicpm = await sidecarCall('minicpm_status');
			const d = downloadInfo();
			if (d.error) {
				status = `Download failed: ${d.error}`;
				if (poll) clearInterval(poll);
			} else if (d.active) {
				const tot = d.total ? ` / ${(d.total / 1e6).toFixed(0)} MB` : '';
				status = `Downloading MiniCPM… ${((d.bytes || 0) / 1e6).toFixed(1)} MB${tot}`;
			} else if (minicpm?.gguf_present) {
				status = 'MiniCPM GGUF is ready. Click Start local.';
				if (poll) clearInterval(poll);
				await refreshNodes();
			}
		}, 800);
	}

	async function startMini() {
		status = 'Starting llama-server…';
		const r = await sidecarCall('minicpm_start');
		status = r.ok === false ? String(r.error) : 'Local MiniCPM is running.';
		await refreshNodes();
	}
</script>

<h1>Ask</h1>
<p class="lead">
	Tokenized Intelligence: specialised Smart nodes answer from your encrypted workspace. Network
	turns settle in BZT. Local MiniCPM runs on this machine (text/coding, not images).
</p>

<div class="ask-shell">
	<aside class="ask-side">
		<strong>Suitable nodes</strong>
		{#if needed.length}
			<div class="row">
				{#each needed as tag}
					<span class="chip">{tag}</span>
				{/each}
			</div>
		{/if}
		<button class="ghost" onclick={() => refreshNodes(draft)}>Refresh</button>
		{#if nodes.length === 0}
			<p class="meta">Looking up Directory nodes on the live network…</p>
			{#if discoverError}<pre>{discoverError}</pre>{/if}
		{/if}
		{#each nodes as n}
			<button class="node-card" class:active={selected?.node_id === n.node_id} onclick={() => pick(n)}>
				<div>{n.label || n.node_id || n.ip}</div>
				<div class="caps">
					{capList(n)} · {n.price_per_query ?? '?'} BZT
					{#if n.suitability != null}
						· score {n.suitability}
					{/if}
				</div>
			</button>
		{/each}
		{#if minicpm}
			<div class="caps">
				MiniCPM GGUF {minicpm.gguf_present ? 'present' : 'missing'} · llama-server
				{minicpm.llama_server ? 'found' : 'not on PATH'} ·
				{minicpm.running ? 'running' : 'stopped'}
			</div>
			<div class="row">
				<button class="ghost" onclick={downloadMini} disabled={Boolean(downloadInfo().active)}>
					{downloadInfo().active ? 'Downloading…' : 'Download model'}
				</button>
				<button class="ghost" onclick={startMini}>Start local</button>
			</div>
		{/if}
	</aside>
	<section class="ask-main">
		<div class="messages">
			{#if messages.length === 0}
				<p class="lead">
					Select a Smart node (or Local MiniCPM), optionally index a PDF/text file, then send.
					The first network Ask downloads the embedding model in-app.
				</p>
			{/if}
			{#each messages as m}
				<div class="bubble {m.role}">
					{m.content}
					{#if m.role === 'assistant'}
						<div class="meta">
							{#if m.local}Local MiniCPM · 0 BZT{:else}{m.cost ?? 0} BZT{/if}
							{#if m.tx_hash} · tx {m.tx_hash.slice(0, 10)}…{/if}
							{#if m.sources && m.sources.length} · {m.sources.length} citations{/if}
							{#if m.verification}
								· interpretable check
								{JSON.stringify(m.verification)}
							{/if}
						</div>
					{/if}
				</div>
			{/each}
			{#if busy}
				<div class="meta">Working…</div>
			{/if}
		</div>
		<div class="composer">
			{#if status}<div class="meta">{status}</div>{/if}
			<div class="row">
				<input type="text" bind:value={attachPath} placeholder="Absolute path to PDF or text file" />
				<button class="ghost" onclick={indexAttach}>Index into node</button>
			</div>
			<textarea bind:value={draft} placeholder="Message…" onkeydown={(e) => e.key === 'Enter' && !e.shiftKey && (e.preventDefault(), send())}></textarea>
			<div class="row">
				<button class="primary" onclick={send} disabled={busy}>Send</button>
				<button
					class="ghost"
					onclick={() => {
						messages = [];
						threadId = undefined;
					}}>New conversation</button
				>
			</div>
		</div>
	</section>
</div>
