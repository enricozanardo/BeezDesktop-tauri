<script lang="ts">
	import { page } from '$app/state';
	import { goto } from '$app/navigation';
	import favicon from '#lib/assets/favicon.svg';
	import {
		appVersion,
		live,
		notes,
		startLive,
		stopLive,
		unreadCount,
		markAllRead,
		markRead,
		clearNotes,
		refreshLive,
		sidecarCall,
		refreshJobs
	} from '#lib';
	import type { Note } from '#lib';
	import '#lib/theme.css';

	let { children } = $props();
	let version = $state('0.2.1');
	let panelOpen = $state(false);

	const links = [
		{ href: '/', label: 'Home' },
		{ href: '/smart', label: 'Ask' },
		{ href: '/knowledge', label: 'Knowledge' },
		{ href: '/wallet', label: 'Wallet' },
		{ href: '/files', label: 'Files' },
		{ href: '/transactions', label: 'Transactions' },
		{ href: '/blockchain', label: 'Blockchain' },
		{ href: '/network', label: 'Network' },
		{ href: '/settings', label: 'Settings' }
	];

	const unread = $derived(unreadCount());
	const runningJobs = $derived(live.jobs.filter((j) => j.status === 'running'));
	const pendingCount = $derived(Array.isArray(live.ledger?.pending) ? (live.ledger.pending as unknown[]).length : 0);
	const incomingCount = $derived(live.incoming.length);

	$effect(() => {
		appVersion().then((v: string) => {
			version = v;
			if (typeof document !== 'undefined') {
				document.title = `Beez Desktop Two v${v}`;
			}
		});
		startLive();
		return stopLive;
	});

	function open(n: Note) {
		markRead(n.id);
		panelOpen = false;
		goto(n.href);
	}

	function ago(t: number): string {
		const s = Math.round((Date.now() - t) / 1000);
		if (s < 60) return 'just now';
		if (s < 3600) return `${Math.floor(s / 60)} min ago`;
		if (s < 86400) return `${Math.floor(s / 3600)} h ago`;
		return new Date(t).toLocaleDateString();
	}

	function lastUpdate(): string {
		return live.lastUpdate ? new Date(live.lastUpdate).toLocaleTimeString() : '—';
	}

	async function dismissJob(id: unknown) {
		await sidecarCall('job_dismiss', { id });
		await refreshJobs();
	}
</script>

<svelte:head>
	<link rel="icon" href={favicon} />
	<title>Beez Desktop Two v{version}</title>
</svelte:head>

<div class="shell">
	<aside class="sidebar">
		<div class="brand">
			BEEZ
			<small>Desktop Two v{version}</small>
		</div>
		<nav>
			{#each links as link}
				<a href={link.href} class:active={page.url.pathname === link.href}>
					{link.label}
					{#if link.href === '/files' && incomingCount}<span class="nav-badge">{incomingCount}</span>{/if}
					{#if link.href === '/transactions' && pendingCount}<span class="nav-badge muted">{pendingCount}</span>{/if}
				</a>
			{/each}
		</nav>
		<div class="sidebar-foot">
			{#each runningJobs as j (j.id)}
				<a class="job-pill" href="/smart" title={String(j.stage)}>
					<span class="spinner"></span>
					<span>{String(j.label)}{Number(j.total) > 0 ? ` · ${Math.round((Number(j.done) / Number(j.total)) * 100)}%` : ''}</span>
				</a>
			{/each}
			<button class="bell" class:has-unread={unread > 0} onclick={() => (panelOpen = !panelOpen)}>
				Notifications{#if unread}<span class="nav-badge">{unread}</span>{/if}
			</button>
			<button class="live-status" onclick={refreshLive} title="Refresh now">
				<span class="dot" class:busy={live.refreshing}></span>
				Live · updated {lastUpdate()}
			</button>
		</div>
	</aside>
	<main>
		{@render children()}
	</main>
</div>

{#if panelOpen}
	<div class="notes-backdrop" role="presentation" onclick={() => (panelOpen = false)}></div>
	<section class="notes-panel" aria-label="Notifications">
		<header class="row" style="justify-content:space-between">
			<h2 style="margin:0">Notifications</h2>
			<div class="row">
				<button class="ghost" disabled={!unread} onclick={markAllRead}>Mark all read</button>
				<button class="ghost" disabled={!notes.items.length} onclick={clearNotes}>Clear</button>
			</div>
		</header>
		{#each live.jobs.filter((j) => j.status !== 'running' && j.kind === 'index') as j (j.id)}
			<div class="note">
				<strong>{String(j.label)} — {j.status === 'done' ? 'finished' : 'failed'}</strong>
				<span class="meta">{j.status === 'done' ? 'Indexing result is ready in Ask.' : String((j.result as Record<string, unknown>)?.error || '')}</span>
				<button class="ghost" onclick={() => dismissJob(j.id)}>Dismiss</button>
			</div>
		{/each}
		{#if notes.items.length === 0}
			<p class="meta">
				Nothing yet. You will be told here (and by your desktop, if enabled in Settings) when you receive BZT
				or messages, when your transactions confirm or are rejected, about file transfer requests, and when
				background indexing finishes.
			</p>
		{/if}
		{#each notes.items as n (n.id)}
			<button class="note" class:unread={!n.read} onclick={() => open(n)}>
				<strong>{n.title}</strong>
				<span>{n.body}</span>
				<span class="meta">{ago(n.at)}</span>
			</button>
		{/each}
	</section>
{/if}
