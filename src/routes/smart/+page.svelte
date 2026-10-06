<script lang="ts">
	import { sidecarCall } from '#lib';
	import { open } from '@tauri-apps/plugin-dialog';

	type SmartNode = Record<string, unknown> & {
		node_id?: string;
		ip?: string;
		capabilities?: string[];
		price_per_query?: number;
		price_per_embedding?: number;
		suitability?: number;
		label?: string;
		gguf_present?: boolean;
		running?: boolean;
		llm_backend?: string;
		llm_model?: string;
		reachable?: boolean;
		http_url?: string;
		modalities?: string[];
	};

	type ChatMsg = {
		role: 'user' | 'assistant';
		content: string;
		sources?: unknown[];
		cost?: number;
		estimated_cost?: number;
		verification?: Record<string, unknown> | null;
		tx_hash?: string;
		local?: boolean;
		error?: string;
		code?: string;
		endpoint?: string;
	};

	type Conversation = {
		id: string;
		title: string;
		node_id?: string;
		thread_id?: string;
		messages: ChatMsg[];
		total_cost_bzt: number;
		updated_at: string;
		file_ids?: string[];
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
	let chats = $state<Conversation[]>([]);
	let chatId = $state<string>('');
	let workspace = $state<Record<string, unknown> | null>(null);
	let poll: ReturnType<typeof setInterval> | undefined;

	function capList(n: SmartNode): string {
		const caps = n.capabilities;
		if (Array.isArray(caps)) return caps.join(', ');
		return String(caps || 'generic');
	}

	function isLocal(n: SmartNode | null): boolean {
		return n?.node_id === 'local_minicpm' || n?.llm_backend === 'minicpm_local';
	}

	function estimatedQueryCost(): number {
		if (isLocal(selected)) return 0;
		return Number(selected?.price_per_query ?? 0);
	}

	function newChatId(): string {
		return crypto.randomUUID();
	}

	async function persist() {
		if (!chatId) return;
		const title =
			messages.find((m) => m.role === 'user')?.content.slice(0, 48) || 'New conversation';
		const total = messages.reduce((s, m) => s + Number(m.cost || 0), 0);
		await sidecarCall('chats_save', {
			conversation: {
				id: chatId,
				title,
				node_id: selected?.node_id,
				thread_id: threadId,
				messages,
				file_ids: fileIds,
				total_cost_bzt: total,
				updated_at: new Date().toISOString()
			}
		});
		await loadChats();
	}

	async function loadChats() {
		const r = await sidecarCall('chats_list');
		chats = ((r.conversations as Conversation[]) || []).sort((a, b) =>
			String(b.updated_at || '').localeCompare(String(a.updated_at || ''))
		);
	}

	function startNewChat() {
		chatId = newChatId();
		messages = [];
		threadId = undefined;
		fileIds = [];
		status = '';
	}

	function resumeChat(c: Conversation) {
		chatId = c.id;
		messages = c.messages || [];
		threadId = c.thread_id;
		fileIds = c.file_ids || [];
		const match = nodes.find((n) => n.node_id === c.node_id);
		if (match) selected = match;
	}

	async function deleteChat(id: string) {
		await sidecarCall('chats_delete', { id });
		if (chatId === id) startNewChat();
		await loadChats();
	}

	async function refreshWorkspace() {
		if (!selected || isLocal(selected)) {
			workspace = null;
			return;
		}
		workspace = await sidecarCall('workspace_stats', { node: selected });
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
		await refreshWorkspace();
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

	function runtimeInfo(): { active?: boolean; bytes?: number; total?: number; error?: string } {
		const d = minicpm?.runtime as Record<string, unknown> | undefined;
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
		chatId = newChatId();
		refreshNodes();
		loadChats();
	});

	function pick(n: SmartNode) {
		selected = n;
		refreshWorkspace();
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
				{ role: 'assistant', content: 'No Smart node available yet.', error: 'no node', code: 'no_node' }
			];
			await persist();
			return;
		}
		if (!isLocal(node)) {
			status = `Preparing embeddings, then Ask (~${estimatedQueryCost()} BZT)…`;
			const ready = await sidecarCall('embed_ensure');
			if (ready.ok === false) {
				busy = false;
				messages = [
					...messages,
					{
						role: 'assistant',
						content: String(ready.error),
						error: String(ready.error),
						code: 'embed_failed'
					}
				];
				await persist();
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
			messages = [
				...messages,
				{
					role: 'assistant',
					content: String(result.error),
					error: String(result.error),
					code: String(result.code || '')
				}
			];
			await persist();
			return;
		}
		if (typeof result.thread_id === 'string') threadId = result.thread_id;
		const txFailed = result.code === 'tx_failed' || (result.tx as Record<string, unknown>)?.ok === false;
		messages = [
			...messages,
			{
				role: 'assistant',
				content: String(result.answer || ''),
				sources: (result.sources as unknown[]) || [],
				cost: Number(result.cost || 0),
				estimated_cost: Number(result.estimated_cost ?? estimatedQueryCost()),
				verification: (result.verification as Record<string, unknown>) || null,
				tx_hash: result.tx_hash as string | undefined,
				local: Boolean(result.local),
				code: result.code === 'empty_workspace' ? 'empty_workspace' : txFailed ? 'tx_failed' : undefined,
				endpoint: result.endpoint as string | undefined,
				error: txFailed ? String((result.tx as Record<string, unknown>)?.error || 'settlement failed') : undefined
			}
		];
		await persist();
	}

	async function browseFile() {
		try {
			const picked = await open({
				multiple: false,
				filters: [
					{ name: 'Text and PDF', extensions: ['pdf', 'txt', 'md', 'py', 'json', 'csv', 'log'] }
				]
			});
			if (typeof picked === 'string') attachPath = picked;
		} catch (err) {
			status = `File dialog unavailable: ${String(err)}. Paste an absolute path instead.`;
		}
	}

	async function indexAttach() {
		if (!attachPath || !selected) return;
		if (isLocal(selected)) {
			status = 'Index into a network Smart node, not Local MiniCPM.';
			return;
		}
		const est = await sidecarCall('index_estimate', { path: attachPath, node: selected });
		if (est.ok === false) {
			status = String(est.error);
			return;
		}
		const cost = Number(est.estimated_cost || 0);
		if (!confirm(`Index ${est.chunks} chunks at ~${cost} BZT (${est.price_per_embedding} BZT / embedding)?`)) {
			return;
		}
		busy = true;
		status = `Indexing (~${cost} BZT)…`;
		const ready = await sidecarCall('embed_ensure');
		if (ready.ok === false) {
			busy = false;
			status = String(ready.error);
			return;
		}
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
		status = `Indexed ${fid.slice(0, 8)}… · ${result.chunks ?? (result.result as Record<string, unknown>)?.chunks_indexed} chunks · ${result.cost ?? 0} BZT${result.tx_hash ? ` · tx ${String(result.tx_hash).slice(0, 10)}` : ''}`;
		await refreshWorkspace();
	}

	function startPoll() {
		if (poll) clearInterval(poll);
		poll = setInterval(async () => {
			minicpm = await sidecarCall('minicpm_status');
			const d = downloadInfo();
			const r = runtimeInfo();
			if (d.error) status = `Model download failed: ${d.error}`;
			else if (d.active) {
				const tot = d.total ? ` / ${(d.total / 1e6).toFixed(0)} MB` : '';
				status = `Downloading MiniCPM… ${((d.bytes || 0) / 1e6).toFixed(1)} MB${tot}`;
			} else if (r.error) status = `Runtime install failed: ${r.error}`;
			else if (r.active) {
				const tot = r.total ? ` / ${(r.total / 1e6).toFixed(0)} MB` : '';
				status = `Installing llama-server… ${((r.bytes || 0) / 1e6).toFixed(1)} MB${tot}`;
			} else if (minicpm?.gguf_present && minicpm?.llama_server) {
				status = 'Local MiniCPM runtime and model are ready. Click Start local.';
				if (poll) clearInterval(poll);
				await refreshNodes();
			} else if (!d.active && !r.active) {
				if (poll) clearInterval(poll);
				await refreshNodes();
			}
		}, 800);
	}

	async function downloadMini() {
		status = 'Starting MiniCPM GGUF download…';
		const r = await sidecarCall('minicpm_download');
		status = r.already_present ? 'Model already on disk.' : String(r.message || r.error || 'Downloading…');
		startPoll();
	}

	async function installRuntime() {
		status = 'Installing llama-server into the app (no PATH setup)…';
		const r = await sidecarCall('minicpm_install_runtime');
		status = r.already_present
			? `llama-server ready: ${r.llama_server}`
			: String(r.message || r.error || 'Installing…');
		startPoll();
	}

	async function startMini() {
		status = 'Starting llama-server…';
		const r = await sidecarCall('minicpm_start');
		status = r.ok === false ? String(r.error) : 'Local MiniCPM is running (0 BZT).';
		await refreshNodes();
	}
</script>

<h1>Ask</h1>
<p class="lead">
	1) Create a wallet. 2) Pick a live Smart node, or install Local MiniCPM (runtime + model) here. 3)
	Optionally index a PDF/text into that node’s private workspace. 4) Send a question — network answers
	settle in BZT on-chain. Local MiniCPM is free and does not index the network.
</p>

<div class="ask-shell">
	<aside class="ask-side">
		<strong>Chats</strong>
		<button class="ghost" onclick={startNewChat}>New chat</button>
		{#each chats as c}
			<button class="node-card" class:active={chatId === c.id} onclick={() => resumeChat(c)}>
				<div>{c.title}</div>
				<div class="caps">{c.total_cost_bzt ?? 0} BZT · {String(c.updated_at || '').slice(0, 16)}</div>
			</button>
		{/each}
		{#if chats.length}
			<button
				class="ghost"
				onclick={() => chatId && deleteChat(chatId)}
				disabled={!chats.some((c) => c.id === chatId)}>Delete current</button
			>
		{/if}

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
			<p class="meta">Looking up Directory Smart nodes on the live network…</p>
			{#if discoverError}<pre>{discoverError}</pre>{/if}
		{/if}
		{#each nodes as n}
			<button class="node-card" class:active={selected?.node_id === n.node_id} onclick={() => pick(n)}>
				<div>{n.label || n.node_id || n.ip}</div>
				<div class="caps">
					{capList(n)}
					{#if n.llm_model} · {n.llm_model}{/if}
					· {n.price_per_query ?? 0} BZT / query
					{#if n.price_per_embedding != null} · {n.price_per_embedding} BZT / embed{/if}
					{#if n.reachable === false} · unreachable{/if}
				</div>
			</button>
		{/each}
		{#if minicpm}
			<div class="caps">
				GGUF {minicpm.gguf_present ? 'present' : 'missing'} · llama-server
				{minicpm.llama_server ? 'installed' : 'not installed'} ·
				{minicpm.running ? 'running' : 'stopped'}
			</div>
			<div class="row">
				<button class="ghost" onclick={installRuntime} disabled={Boolean(runtimeInfo().active)}>
					{runtimeInfo().active ? 'Installing runtime…' : 'Install local runtime'}
				</button>
				<button class="ghost" onclick={downloadMini} disabled={Boolean(downloadInfo().active)}>
					{downloadInfo().active ? 'Downloading…' : 'Download model'}
				</button>
				<button class="ghost" onclick={startMini}>Start local</button>
			</div>
		{/if}
		{#if workspace && workspace.ok !== false}
			<p class="meta">
				Workspace files: {workspace.file_count ?? workspace.files ?? workspace.indexed_files ?? '—'}
				{#if Number(workspace.file_count || workspace.chunk_count || 0) === 0}
					— Ask still runs, but retrieval may return no relevant data until you index a file.
				{/if}
			</p>
		{/if}
	</aside>
	<section class="ask-main">
		<div class="messages">
			{#if messages.length === 0}
				<p class="lead">
					Estimated cost for the selected node: <strong>{estimatedQueryCost()} BZT</strong> per Ask
					(0 for Local MiniCPM). Indexing bills separately at the node’s embedding price.
				</p>
			{/if}
			{#each messages as m}
				<div class="bubble {m.role}">
					{m.content}
					{#if m.role === 'assistant'}
						<div class="meta">
							{#if m.local}Local MiniCPM · 0 BZT{:else}
								{m.cost ?? 0} BZT
								{#if m.estimated_cost != null && m.estimated_cost !== m.cost}
									(est. {m.estimated_cost})
								{/if}
							{/if}
							{#if m.tx_hash} · settled {m.tx_hash.slice(0, 10)}…{/if}
							{#if m.code === 'tx_failed'} · answer delivered, settlement failed{/if}
							{#if m.code === 'empty_workspace'} · no indexed chunks for this wallet{/if}
							{#if m.endpoint} · {m.endpoint}{/if}
							{#if m.sources && m.sources.length} · {m.sources.length} citations{/if}
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
				<input type="text" bind:value={attachPath} placeholder="File to index (PDF or text)" />
				<button class="ghost" onclick={browseFile}>Browse</button>
				<button class="ghost" onclick={indexAttach}>Index into node</button>
			</div>
			<textarea
				bind:value={draft}
				placeholder="Message…"
				onkeydown={(e) => e.key === 'Enter' && !e.shiftKey && (e.preventDefault(), send())}
			></textarea>
			<div class="row">
				<button class="primary" onclick={send} disabled={busy}
					>Send · {estimatedQueryCost()} BZT</button
				>
				<button class="ghost" onclick={startNewChat}>New conversation</button>
			</div>
		</div>
	</section>
</div>
