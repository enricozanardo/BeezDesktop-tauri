<script lang="ts">
	import { sidecarCall, WorkspacePicker, live, startJob, refreshJobs, Progress, Pager, shortAddr } from '#lib';
	import type { WorkspaceFile } from '#lib';
	import { open } from '@tauri-apps/plugin-dialog';
	import { untrack } from 'svelte';

	type SmartNode = Record<string, unknown> & {
		node_id?: string;
		instance_id?: string;
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
		llm_available?: boolean;
		llm_unavailable_reason?: string;
		available?: boolean;
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
		mode?: string;
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

	type IndexConfirm = {
		chunks: number;
		cost: number;
		price_per_embedding: number;
		balance: number | null;
		balanceKnown: boolean;
		note: string;
		insufficient: boolean;
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
	let workspaceFiles = $state<WorkspaceFile[]>([]);
	let showDocs = $state(false);
	let indexConfirm = $state<IndexConfirm | null>(null);
	let indexNode = $state<SmartNode | null>(null);
	let estimateJobId = $state<string | null>(null);
	let chatQuery = $state('');
	let chatOffset = $state(0);
	let nodeQuery = $state('');
	let nodeOffset = $state(0);
	let handledJobs = new Set<string>();
	let poll: ReturnType<typeof setInterval> | undefined;

	const CHAT_PAGE = 8;
	const NODE_PAGE = 5;

	const filteredChats = $derived(
		chats.filter((c) => (c.title || '').toLowerCase().includes(chatQuery.trim().toLowerCase()))
	);
	const filteredNodes = $derived(
		nodes.filter((n) => {
			const q = nodeQuery.trim().toLowerCase();
			if (!q) return true;
			return [n.label, n.node_id, n.wallet_address, n.llm_model, capList(n)]
				.map((v) => String(v || '').toLowerCase())
				.some((v) => v.includes(q));
		})
	);
	const estimateJob = $derived(live.jobs.find((j) => j.id === estimateJobId) || null);
	const indexJobs = $derived(live.jobs.filter((j) => j.kind === 'index'));
	const localSteps = $derived({
		runtime: Boolean(minicpm?.llama_server),
		model: Boolean(minicpm?.gguf_present),
		running: Boolean(minicpm?.running)
	});

	function capList(n: SmartNode): string {
		const caps = n.capabilities;
		if (Array.isArray(caps)) return caps.join(', ');
		return String(caps || 'generic');
	}

	function isLocal(n: SmartNode | null): boolean {
		return n?.node_id === 'local_minicpm' || n?.llm_backend === 'minicpm_local';
	}

	function nodeLabel(n: SmartNode | null): string {
		if (!n) return 'No node selected';
		return String(n.label || n.instance_id || n.node_id || 'Smart');
	}

	function nodeWallet(n: SmartNode): string {
		if (isLocal(n)) return 'runs on this computer';
		return n.wallet_address ? `wallet ${shortAddr(n.wallet_address)}` : 'no wallet published';
	}

	function currentChatTitle(): string {
		const saved = chats.find((c) => c.id === chatId);
		if (saved?.title) return saved.title;
		const first = messages.find((m) => m.role === 'user')?.content?.slice(0, 48);
		return first || 'New conversation';
	}

	function chatInList(): boolean {
		return chats.some((c) => c.id === chatId);
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
		indexConfirm = null;
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
			workspaceFiles = [];
			return;
		}
		const ws = await sidecarCall('workspace_stats', { node: selected });
		workspaceFiles = Array.isArray(ws.files) ? (ws.files as WorkspaceFile[]) : [];
	}

	function docName(id: string): string {
		return workspaceFiles.find((f) => f.file_id === id)?.file_name || id.slice(0, 8);
	}

	async function removeDoc(f: WorkspaceFile) {
		if (!selected) return;
		if (
			!confirm(
				`Remove “${f.file_name || f.file_id}” from ${nodeLabel(selected)}? Its index is deleted; listings that use it stop answering from it.`
			)
		)
			return;
		busy = true;
		const r = await sidecarCall('workspace_remove', { node: selected, file_id: f.file_id });
		busy = false;
		status = r.ok === false ? String(r.error) : `Removed ${f.file_name || f.file_id}.`;
		fileIds = fileIds.filter((id) => id !== f.file_id);
		await refreshWorkspace();
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
		const saved = chats.find((c) => c.id === chatId);
		if (saved?.node_id) {
			const byChat = nodes.find((n) => n.node_id === saved.node_id);
			if (byChat) selected = byChat;
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
				code:
					result.code === 'llm_no_credit'
						? 'llm_no_credit'
						: result.code === 'empty_workspace'
							? 'empty_workspace'
							: txFailed
								? 'tx_failed'
								: undefined,
				endpoint: result.endpoint as string | undefined,
				mode: typeof result.mode === 'string' ? result.mode : undefined,
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
			status = 'Local MiniCPM cannot index documents. Pick a network Smart node to index.';
			return;
		}
		const wallet = await sidecarCall('wallet_status');
		if (wallet.has_wallet === false || wallet.ok === false) {
			status = 'Create a wallet before indexing (Wallet section).';
			return;
		}
		status = '';
		indexConfirm = null;
		indexNode = selected;
		estimateJobId = await startJob('index_estimate', { path: attachPath, node: selected });
		if (!estimateJobId) status = 'Could not start the cost estimate.';
	}

	$effect(() => {
		const j = estimateJob;
		if (!j || j.status === 'running') return;
		untrack(() => {
			estimateJobId = null;
			sidecarCall('job_dismiss', { id: j.id }).then(refreshJobs);
			const est = (j.result as Record<string, unknown>) || {};
			if (est.ok === false) status = String(est.error);
			else showIndexConfirm(est);
		});
	});

	$effect(() => {
		for (const j of indexJobs) {
			const id = String(j.id);
			if (j.status === 'running' || handledJobs.has(id)) continue;
			handledJobs.add(id);
			refreshWorkspace();
		}
	});

	function showIndexConfirm(est: Record<string, unknown>) {
		const cost = Number(est.estimated_cost || 0);
		const note =
			est.truncated || est.chunk_capped
				? `Large file: only ~${est.chunks} chunks (first ~${est.max_chars} characters) will be indexed for Ask. Full encrypted storage is Files → Upload.`
				: '';
		let balance: number | null = null;
		let balanceKnown = false;
		const ledger = live.ledger;
		if (ledger && ledger.ok !== false && ledger.balance != null && ledger.balance !== '') {
			const n = Number(ledger.balance);
			if (!Number.isNaN(n)) {
				balance = n;
				balanceKnown = true;
			}
		}

		const insufficient = balanceKnown && balance != null && balance < cost;
		indexConfirm = {
			chunks: Number(est.chunks || 0),
			cost,
			price_per_embedding: Number(est.price_per_embedding || 0),
			balance,
			balanceKnown,
			note,
			insufficient
		};
		if (insufficient) {
			status = `Insufficient balance: need ~${cost} BZT, wallet has ${balance} BZT.`;
		} else if (!balanceKnown) {
			status = 'Could not read wallet balance; you may still proceed.';
		} else {
			status = '';
		}
	}

	function cancelIndexConfirm() {
		indexConfirm = null;
	}

	async function proceedIndexConfirm() {
		const node = indexNode || selected;
		if (!indexConfirm || !node || indexConfirm.insufficient) return;
		indexConfirm = null;
		const id = await startJob('index', { path: attachPath, node });
		status = id
			? 'Indexing runs in the background: keep asking or switch sections. You will be notified when it finishes.'
			: 'Could not start indexing.';
		attachPath = '';
	}

	async function dismissJob(id: unknown) {
		await sidecarCall('job_dismiss', { id });
		await refreshJobs();
	}

	function jobSummary(j: Record<string, unknown>): string {
		const r = (j.result as Record<string, unknown>) || {};
		if (j.status === 'error') return `Failed: ${String(r.error || 'unknown error')}`;
		const cap = r.truncated || r.chunk_capped ? ' · large file capped for Ask' : '';
		return `${r.chunks ?? 0} chunks · ${r.cost ?? 0} BZT${r.tx_hash ? ` · tx ${String(r.tx_hash).slice(0, 10)}…` : ''}${cap}`;
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
				status = minicpm?.running ? '' : 'Runtime and model are ready. Start Local MiniCPM in step 3.';
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

	let localBusy = $state('');

	async function startMini() {
		localBusy = 'Starting Local MiniCPM (up to 30 s)…';
		const r = await sidecarCall('minicpm_start');
		localBusy = '';
		status = r.ok === false ? String(r.error) : 'Local MiniCPM is running. Questions are free.';
		await refreshNodes();
	}

	async function stopMini() {
		localBusy = 'Stopping…';
		const r = await sidecarCall('minicpm_stop');
		localBusy = '';
		status = r.ok === false ? String(r.error) : 'Local MiniCPM stopped.';
		minicpm = await sidecarCall('minicpm_status');
	}

	async function resetMini() {
		if (!confirm('Stop Local MiniCPM and delete the downloaded model and runtime (about 1.5 GB)? You can set it up again afterwards.')) return;
		localBusy = 'Resetting…';
		const r = await sidecarCall('minicpm_reset');
		localBusy = '';
		status = r.ok === false ? String(r.error) : 'Local MiniCPM was reset. Start again from step 1.';
		minicpm = await sidecarCall('minicpm_status');
	}

	function mb(n?: number): string {
		return `${((n || 0) / 1e6).toFixed(0)} MB`;
	}
</script>

<h1>Ask</h1>
<p class="lead">
	Pick a Smart node (or Local MiniCPM on this computer) and ask anything. Optionally index a document
	on a network node so answers cite it; indexing runs in the background. Full encrypted file storage
	is in Files.
</p>

{#if indexConfirm}
	<div class="confirm-backdrop" role="presentation">
		<div class="confirm-panel" role="dialog" aria-labelledby="index-confirm-title">
			<strong id="index-confirm-title">Confirm indexing</strong>
			<p>
				Index <strong>{indexConfirm.chunks}</strong> chunks at
				<strong>~{indexConfirm.cost}</strong> BZT
				({indexConfirm.price_per_embedding} BZT per chunk) on
				<strong>{nodeLabel(indexNode || selected)}</strong>?
			</p>
			<p class="meta">Indexing runs in the background: you can keep asking and move between sections while it works.</p>
			{#if indexConfirm.balanceKnown}
				<p class="meta">
					Wallet balance: <strong>{indexConfirm.balance}</strong> BZT
					{#if indexConfirm.insufficient}
						<span class="danger"> — insufficient for this index</span>
					{/if}
				</p>
			{:else}
				<p class="meta">Wallet balance could not be read; proceed only if you have enough BZT.</p>
			{/if}
			{#if indexConfirm.note}
				<p class="meta">{indexConfirm.note}</p>
			{/if}
			<p class="meta">You can Ask general questions without indexing.</p>
			<div class="row">
				<button class="ghost" onclick={cancelIndexConfirm}>Cancel</button>
				<button
					class="primary"
					onclick={proceedIndexConfirm}
					disabled={indexConfirm.insufficient || busy}
				>
					{indexConfirm.insufficient ? 'Insufficient BZT' : `Index · ~${indexConfirm.cost} BZT`}
				</button>
			</div>
		</div>
	</div>
{/if}

<div class="ask-shell">
	<aside class="ask-side">
		<div class="row" style="justify-content:space-between">
			<strong>Chats</strong>
			<button class="ghost" onclick={startNewChat}>New chat</button>
		</div>
		{#if chats.length > CHAT_PAGE || chatQuery}
			<input type="search" bind:value={chatQuery} oninput={() => (chatOffset = 0)} placeholder="Search chats…" />
		{/if}
		{#if chatId && !chatInList()}
			<button class="node-card active ghost-chat" disabled>
				<div>New conversation</div>
				<div class="caps">unsaved · current</div>
			</button>
		{/if}
		{#each filteredChats.slice(chatOffset, chatOffset + CHAT_PAGE) as c (c.id)}
			<button class="node-card" class:active={chatId === c.id} onclick={() => resumeChat(c)}>
				<div>{c.title}</div>
				<div class="caps">{c.total_cost_bzt ?? 0} BZT · {String(c.updated_at || '').slice(0, 16).replace('T', ' ')}</div>
			</button>
		{/each}
		{#if chatQuery && filteredChats.length === 0}<p class="meta">No chat matches.</p>{/if}
		<Pager total={filteredChats.length} limit={CHAT_PAGE} bind:offset={chatOffset} />
		{#if chats.length}
			<button
				class="ghost"
				onclick={() => chatId && deleteChat(chatId)}
				disabled={!chats.some((c) => c.id === chatId)}>Delete current chat</button
			>
		{/if}

		<div class="row" style="justify-content:space-between; margin-top:0.5rem">
			<strong>Suitable nodes</strong>
			<button class="ghost" onclick={() => refreshNodes(draft)}>Refresh</button>
		</div>
		{#if needed.length}
			<div class="row">
				{#each needed as tag}
					<span class="chip">{tag}</span>
				{/each}
			</div>
		{/if}
		{#if nodes.length > NODE_PAGE || nodeQuery}
			<input type="search" bind:value={nodeQuery} oninput={() => (nodeOffset = 0)} placeholder="Search nodes, models, wallets…" />
		{/if}
		{#if nodes.length === 0}
			<p class="meta">Looking up Directory Smart nodes on the live network…</p>
			{#if discoverError}<pre>{discoverError}</pre>{/if}
		{/if}
		{#each filteredNodes.slice(nodeOffset, nodeOffset + NODE_PAGE) as n (n.node_id)}
			<button class="node-card" class:active={selected?.node_id === n.node_id} onclick={() => pick(n)}>
				<div>{nodeLabel(n)}</div>
				<div class="caps mono">{nodeWallet(n)}</div>
				<div class="caps">
					{capList(n)}
					{#if n.llm_model} · {n.llm_model}{/if}
					· {n.price_per_query ?? 0} BZT / question
					{#if n.price_per_embedding != null && !isLocal(n)} · {n.price_per_embedding} BZT / indexed chunk{/if}
					{#if n.reachable === false} · unreachable{/if}
					{#if isLocal(n)} · {localSteps.running ? 'running' : 'not running'}{/if}
					{#if n.llm_available === false || n.available === false}
						· LLM unavailable
						{#if n.llm_unavailable_reason}
							({String(n.llm_unavailable_reason).slice(0, 48)})
						{/if}
					{/if}
				</div>
			</button>
		{/each}
		<Pager total={filteredNodes.length} limit={NODE_PAGE} bind:offset={nodeOffset} />
		{#if selected && !isLocal(selected)}
			<p class="meta">
				{workspaceFiles.length} document(s) indexed on this node.
				{#if workspaceFiles.length === 0}Ask still answers general questions.{/if}
			</p>
		{/if}
	</aside>
	<section class="ask-main">
		<div class="ask-session">
			<div>
				<span class="ask-session-label">Chat</span>
				<strong>{currentChatTitle()}</strong>
			</div>
			<div>
				<span class="ask-session-label">Node</span>
				<strong>{nodeLabel(selected)}</strong>
			</div>
		</div>

		{#if isLocal(selected) && minicpm}
			<div class="stack" style="padding:1rem 1.25rem; border-bottom:1px solid var(--border)">
				<div class="row" style="justify-content:space-between">
					<strong>Local MiniCPM setup</strong>
					<button class="danger" onclick={resetMini} disabled={Boolean(localBusy) || Boolean(downloadInfo().active) || Boolean(runtimeInfo().active) || !(localSteps.runtime || localSteps.model)}>Reset</button>
				</div>
				<p class="meta" style="margin:0">
					Runs a small language model on this computer: free and private, no indexing. Do the three steps once; afterwards only step 3 is needed.
				</p>
				<div class="steps" style="margin:0">
					<div class="step" class:done={localSteps.runtime}>
						<div class="step-num">{localSteps.runtime ? '✓' : '1'}</div>
						<div class="stack" style="gap:0.4rem; flex:1">
							<strong>Install the runtime</strong>
							<p>llama-server, about 30 MB, installed inside the app.</p>
							{#if runtimeInfo().active}
								<Progress done={runtimeInfo().bytes} total={runtimeInfo().total} label={`${mb(runtimeInfo().bytes)}${runtimeInfo().total ? ` of ${mb(runtimeInfo().total)}` : ''}`} />
							{:else if runtimeInfo().error}
								<p class="error">{runtimeInfo().error}</p>
							{/if}
							<button class="ghost" onclick={installRuntime} disabled={localSteps.runtime || Boolean(runtimeInfo().active)}>
								{localSteps.runtime ? 'Installed' : runtimeInfo().active ? 'Installing…' : 'Install runtime'}
							</button>
						</div>
					</div>
					<div class="step" class:done={localSteps.model}>
						<div class="step-num">{localSteps.model ? '✓' : '2'}</div>
						<div class="stack" style="gap:0.4rem; flex:1">
							<strong>Download the model</strong>
							<p>MiniCPM 2B, about 1.4 GB, stored on this computer.</p>
							{#if downloadInfo().active}
								<Progress done={downloadInfo().bytes} total={downloadInfo().total} label={`${mb(downloadInfo().bytes)}${downloadInfo().total ? ` of ${mb(downloadInfo().total)}` : ''}`} />
							{:else if downloadInfo().error}
								<p class="error">{downloadInfo().error}</p>
							{/if}
							<button class="ghost" onclick={downloadMini} disabled={localSteps.model || Boolean(downloadInfo().active)}>
								{localSteps.model ? 'Downloaded' : downloadInfo().active ? 'Downloading…' : 'Download model'}
							</button>
						</div>
					</div>
					<div class="step" class:done={localSteps.running}>
						<div class="step-num">{localSteps.running ? '✓' : '3'}</div>
						<div class="stack" style="gap:0.4rem; flex:1">
							<strong>{localSteps.running ? 'Running' : 'Start'}</strong>
							<p>{localSteps.running ? 'Ready for questions on this computer.' : 'Starts the model; it also starts by itself on your first question.'}</p>
							{#if localBusy}<Progress label={localBusy} />{/if}
							{#if localSteps.running}
								<button class="ghost" onclick={stopMini} disabled={Boolean(localBusy) || minicpm.owned === false}>Stop</button>
								{#if minicpm.owned === false}<p class="meta">Started outside this app; stop it there.</p>{/if}
							{:else}
								<button class="primary" onclick={startMini} disabled={!localSteps.runtime || !localSteps.model || Boolean(localBusy)}>Start</button>
							{/if}
						</div>
					</div>
				</div>
			</div>
		{/if}

		<div class="messages">
			{#if messages.length === 0}
				<p class="lead">
					Estimated cost for the selected node: <strong>{estimatedQueryCost()} BZT</strong> per question
					(0 for Local MiniCPM). Indexing bills separately at the node’s per-chunk price.
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
							{#if m.code === 'llm_no_credit'}
								· provider out of credits — try another node
							{:else if m.mode === 'general' || m.code === 'empty_workspace'}
								· general knowledge (no matching indexed docs)
							{:else if m.mode === 'rag'}
								· from indexed docs
							{/if}
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
			{#each indexJobs as j (j.id)}
				<div class="row" style="align-items:flex-start">
					<div class="grow">
						{#if j.status === 'running'}
							<Progress done={Number(j.done)} total={Number(j.total)} label={`${String(j.label)} · ${String(j.stage)}${Number(j.total) ? ` (${j.done}/${j.total} chunks)` : ''}`} />
						{:else}
							<span class="chip {j.status === 'done' ? 'ok' : 'danger'}">{j.status === 'done' ? 'indexed' : 'failed'}</span>
							<span class="meta">{String(j.label).replace('Indexing ', '')} · {jobSummary(j)}</span>
						{/if}
					</div>
					{#if j.status !== 'running'}<button class="ghost" onclick={() => dismissJob(j.id)}>Dismiss</button>{/if}
				</div>
			{/each}
			{#if selected && !isLocal(selected)}
				<div class="row">
					<span class="meta" style="margin:0">
						Answer from:
						{#if fileIds.length === 0}
							<strong>all {workspaceFiles.length} indexed document(s)</strong>
						{:else}
							<strong>{fileIds.map(docName).join(', ')}</strong>
						{/if}
					</span>
					<button class="ghost" onclick={() => (showDocs = !showDocs)}>
						{showDocs ? 'Hide documents' : 'Choose documents'}
					</button>
				</div>
				{#if showDocs}
					{#if workspaceFiles.length}
						<WorkspacePicker files={workspaceFiles} bind:selected={fileIds} {busy} onremove={removeDoc} />
						<p class="meta" style="margin:0">No selection = search all documents.</p>
					{:else}
						<p class="meta" style="margin:0">No documents indexed on this node yet. Index one below.</p>
					{/if}
				{/if}
				<div class="row">
					<input type="text" class="grow" bind:value={attachPath} placeholder="File to index (PDF or text)" />
					<button class="ghost" onclick={browseFile}>Browse</button>
					<button class="ghost" onclick={indexAttach} disabled={!attachPath || Boolean(estimateJobId)}>Index into node</button>
				</div>
				{#if estimateJob}
					<Progress done={Number(estimateJob.done)} total={Number(estimateJob.total)} label={`Calculating the cost · ${String(estimateJob.stage)}`} />
				{/if}
			{:else if isLocal(selected)}
				<p class="meta" style="margin:0">Local MiniCPM answers from its own knowledge; documents can only be indexed on network Smart nodes.</p>
			{/if}
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
