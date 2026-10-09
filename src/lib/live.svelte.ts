import { sidecarCall } from './sidecar';

type Rec = Record<string, unknown>;

export type Note = {
	id: string;
	at: number;
	kind: NoteKind;
	title: string;
	body: string;
	href: string;
	read: boolean;
};

export type NoteKind = 'payment' | 'message' | 'confirmed' | 'dropped' | 'ownership' | 'job';

export const NOTE_KINDS: { kind: NoteKind; label: string }[] = [
	{ kind: 'payment', label: 'BZT received' },
	{ kind: 'message', label: 'Messages received' },
	{ kind: 'confirmed', label: 'My transactions confirmed' },
	{ kind: 'dropped', label: 'My transactions rejected by the network' },
	{ kind: 'ownership', label: 'File transfer requests and completions' },
	{ kind: 'job', label: 'Background jobs finished (indexing)' }
];

export type Settings = {
	refreshSecs: number;
	desktop: boolean;
	kinds: Record<NoteKind, boolean>;
};

const SETTINGS_KEY = 'beez.settings.v1';
const NOTES_KEY = 'beez.notes.v1';
const MAX_NOTES = 200;
const JOB_POLL_MS = 1200;
const DROP_AFTER_HEIGHTS = 2;

function loadJson<T>(key: string, fallback: T): T {
	try {
		const raw = localStorage.getItem(key);
		return raw ? { ...fallback, ...JSON.parse(raw) } : fallback;
	} catch {
		return fallback;
	}
}

const defaultSettings: Settings = {
	refreshSecs: 20,
	desktop: true,
	kinds: { payment: true, message: true, confirmed: true, dropped: true, ownership: true, job: true }
};

export const settings = $state<Settings>(loadJson(SETTINGS_KEY, defaultSettings));

export const live = $state({
	ledger: null as Rec | null,
	incoming: [] as Rec[],
	outgoing: [] as Rec[],
	jobs: [] as Rec[],
	lastUpdate: 0,
	refreshing: false
});

export const notes = $state({ items: loadNotes() });

function loadNotes(): Note[] {
	try {
		const raw = localStorage.getItem(NOTES_KEY);
		return raw ? (JSON.parse(raw) as Note[]) : [];
	} catch {
		return [];
	}
}

export function saveSettings() {
	localStorage.setItem(SETTINGS_KEY, JSON.stringify(settings));
	restartTimer();
}

function persistNotes() {
	localStorage.setItem(NOTES_KEY, JSON.stringify(notes.items.slice(0, MAX_NOTES)));
}

export function unreadCount(): number {
	return notes.items.filter((n) => !n.read).length;
}

export function markAllRead() {
	notes.items = notes.items.map((n) => ({ ...n, read: true }));
	persistNotes();
}

export function markRead(id: string) {
	notes.items = notes.items.map((n) => (n.id === id ? { ...n, read: true } : n));
	persistNotes();
}

export function clearNotes() {
	notes.items = [];
	persistNotes();
}

let desktopReady: boolean | null = null;

async function desktopNotify(title: string, body: string) {
	try {
		const mod = await import('@tauri-apps/plugin-notification');
		if (desktopReady === null) {
			desktopReady = await mod.isPermissionGranted();
			if (!desktopReady) desktopReady = (await mod.requestPermission()) === 'granted';
		}
		if (desktopReady) mod.sendNotification({ title, body });
	} catch {
		desktopReady = false;
	}
}

export async function testDesktopNotification(): Promise<boolean> {
	desktopReady = null;
	await desktopNotify('Beez Desktop', 'Desktop notifications are working.');
	return desktopReady === true;
}

export function notify(kind: NoteKind, title: string, body: string, href: string, key: string) {
	if (!settings.kinds[kind]) return;
	if (notes.items.some((n) => n.id === key)) return;
	notes.items = [{ id: key, at: Date.now(), kind, title, body, href, read: false }, ...notes.items].slice(0, MAX_NOTES);
	persistNotes();
	if (settings.desktop) desktopNotify(title, body);
}

// ---- event diffing --------------------------------------------------------

type Watch = {
	address: string;
	seenTx: Set<string>;
	pending: Map<string, Rec>;
	vanished: Map<string, { tx: Rec; height: number }>;
	requests: Set<string>;
	primed: boolean;
};

const watchKey = (a: string) => `beez.watch.v1.${a}`;

function loadWatch(address: string): Watch {
	const w: Watch = {
		address,
		seenTx: new Set(),
		pending: new Map(),
		vanished: new Map(),
		requests: new Set(),
		primed: false
	};
	try {
		const raw = localStorage.getItem(watchKey(address));
		if (raw) {
			const s = JSON.parse(raw);
			w.seenTx = new Set(s.seenTx || []);
			w.pending = new Map(Object.entries(s.pending || {}));
			w.vanished = new Map(Object.entries(s.vanished || {}));
			w.requests = new Set(s.requests || []);
			w.primed = true;
		}
	} catch {
		/* start fresh */
	}
	return w;
}

function saveWatch(w: Watch) {
	localStorage.setItem(
		watchKey(w.address),
		JSON.stringify({
			seenTx: [...w.seenTx].slice(-2000),
			pending: Object.fromEntries(w.pending),
			vanished: Object.fromEntries(w.vanished),
			requests: [...w.requests]
		})
	);
}

let watch: Watch | null = null;

const TX_LABEL: Record<string, string> = {
	normal: 'Transfer',
	transfer: 'Transfer',
	upload: 'File upload',
	smart_index: 'Ask indexing',
	smart_query: 'Ask question',
	knowledge_publish: 'Knowledge listing',
	knowledge_query: 'Knowledge question',
	knowledge_purchase: 'Knowledge purchase',
	ownership_request: 'Ownership request',
	ownership_accept: 'Ownership transfer',
	ownership_reject: 'Ownership decline',
	ownership_cancel: 'Ownership withdrawal',
	update_digital_asset_price: 'Listing price',
	update_digital_asset_visibility: 'Listing visibility'
};

export function txLabel(tx: Rec): string {
	const t = String(tx.type || 'normal');
	return TX_LABEL[t] || t.replaceAll('_', ' ');
}

export function shortAddr(a: unknown): string {
	const s = String(a || '');
	return s.length > 16 ? `${s.slice(0, 8)}…${s.slice(-6)}` : s;
}

function diffLedger(w: Watch, ledger: Rec) {
	const history = Array.isArray(ledger.transactions) ? (ledger.transactions as Rec[]) : [];
	const pending = Array.isArray(ledger.pending) ? (ledger.pending as Rec[]) : [];
	const height = Number(ledger.synced_height ?? -1);
	const silent = !w.primed;

	for (const tx of history) {
		const h = String(tx.tx_hash || '');
		if (!h || w.seenTx.has(h)) continue;
		w.seenTx.add(h);
		w.vanished.delete(h);
		const wasMine = w.pending.has(h);
		w.pending.delete(h);
		if (silent) continue;
		const type = String(tx.type || 'normal');
		const memo = String(tx.memo || '');
		if ((type === 'normal' || type === 'transfer') && tx.direction === 'received') {
			const amount = Number(tx.amount_numeric || 0);
			if (memo) {
				notify('message', `Message from ${shortAddr(tx.counterparty)}`, amount > 0 ? `${memo} (+${amount} BZT)` : memo, '/transactions', `rx:${h}`);
			} else if (amount > 0) {
				notify('payment', `Received ${amount} BZT`, `From ${shortAddr(tx.counterparty)}`, '/transactions', `rx:${h}`);
			}
		} else if (type === 'ownership_request' && tx.direction === 'received') {
			notify('ownership', 'New file transfer request', 'Open Files → Transfers to decide.', '/files', `own:${h}`);
		} else if (type === 'ownership_accept') {
			const sold = tx.direction === 'received';
			notify('ownership', sold ? 'File sold' : 'File transfer completed', sold ? `You received ${tx.amount}.` : 'The file is now in My files.', '/files', `own:${h}`);
		} else if (wasMine) {
			notify('confirmed', `${txLabel(tx)} confirmed`, `In block ${tx.block_height}.`, '/transactions', `ok:${h}`);
		}
	}

	const nowPending = new Set<string>();
	for (const tx of pending) {
		const h = String(tx.tx_hash || '');
		if (!h) continue;
		nowPending.add(h);
		if (!w.seenTx.has(h)) w.pending.set(h, { type: tx.type, amount: tx.amount });
	}
	for (const [h, tx] of w.pending) {
		if (!nowPending.has(h) && !w.vanished.has(h)) w.vanished.set(h, { tx, height });
	}
	for (const [h, v] of w.vanished) {
		if (w.seenTx.has(h)) {
			w.vanished.delete(h);
			continue;
		}
		if (height >= 0 && v.height >= 0 && height >= v.height + DROP_AFTER_HEIGHTS) {
			w.vanished.delete(h);
			w.pending.delete(h);
			notify('dropped', `${txLabel(v.tx)} was rejected`, 'It left the mempool without being mined. Your balance was not charged.', '/transactions', `drop:${h}`);
		}
	}
}

function diffRequests(w: Watch, incoming: Rec[]) {
	for (const r of incoming) {
		const id = String(r.request_id || '');
		if (!id || w.requests.has(id)) continue;
		w.requests.add(id);
		if (!w.primed) continue;
		const buyerAsks = String(r.initiated_by || '') === String(r.new_owner_address || '');
		notify(
			'ownership',
			buyerAsks ? 'Someone wants to buy your file' : 'You received a file offer',
			`“${r.file_name || 'file'}” for ${r.asking_price ?? 0} BZT`,
			'/files',
			`req:${id}`
		);
	}
}

const jobStatus = new Map<string, string>();

function diffJobs(jobs: Rec[]) {
	for (const j of jobs) {
		const id = String(j.id);
		const status = String(j.status);
		const before = jobStatus.get(id);
		jobStatus.set(id, status);
		if (before === 'running' && status !== 'running' && j.kind === 'index') {
			const r = (j.result as Rec) || {};
			if (status === 'done') notify('job', `${j.label} finished`, `${r.chunks} chunks indexed for ${r.cost} BZT.`, '/smart', `job:${id}`);
			else notify('job', `${j.label} failed`, String(r.error || 'Unknown error'), '/smart', `job:${id}`);
		}
	}
}

// ---- polling --------------------------------------------------------------

const listeners = new Set<() => void | Promise<void>>();

/** Register a page refresher called on every live tick; returns the unsubscribe function. */
export function onLiveTick(fn: () => void | Promise<void>): () => void {
	listeners.add(fn);
	return () => listeners.delete(fn);
}

export async function refreshLive() {
	if (live.refreshing) return;
	live.refreshing = true;
	try {
		const [ledger, pend] = await Promise.all([sidecarCall('wallet_ledger'), sidecarCall('ownership_pending')]);
		live.ledger = ledger;
		if (pend.ok) {
			live.incoming = (pend.incoming as Rec[]) || [];
			live.outgoing = (pend.outgoing as Rec[]) || [];
		}
		const address = String(ledger.address || '');
		if (address && ledger.ok !== false) {
			if (!watch || watch.address !== address) watch = loadWatch(address);
			diffLedger(watch, ledger);
			if (pend.ok) diffRequests(watch, live.incoming);
			watch.primed = true;
			saveWatch(watch);
		}
		live.lastUpdate = Date.now();
		await Promise.all([...listeners].map((fn) => Promise.resolve(fn()).catch(() => undefined)));
	} finally {
		live.refreshing = false;
	}
}

export async function refreshJobs() {
	const r = await sidecarCall('jobs_list');
	live.jobs = (r.jobs as Rec[]) || [];
	diffJobs(live.jobs);
}

let timer: ReturnType<typeof setInterval> | null = null;
let jobTimer: ReturnType<typeof setInterval> | null = null;

function restartTimer() {
	if (timer) clearInterval(timer);
	timer = setInterval(refreshLive, Math.max(5, settings.refreshSecs) * 1000);
}

/** Start background polling (idempotent); call once from the root layout. */
export function startLive() {
	if (timer) return;
	refreshLive();
	refreshJobs();
	restartTimer();
	jobTimer = setInterval(() => {
		if (live.jobs.some((j) => j.status === 'running')) refreshJobs();
	}, JOB_POLL_MS);
}

/** Start a native background job and begin tracking it. */
export async function startJob(kind: string, params: Rec): Promise<string | null> {
	const r = await sidecarCall('job_start', { kind, params });
	if (!r.ok) return null;
	await refreshJobs();
	return String(r.id);
}

export function stopLive() {
	if (timer) clearInterval(timer);
	if (jobTimer) clearInterval(jobTimer);
	timer = jobTimer = null;
}
