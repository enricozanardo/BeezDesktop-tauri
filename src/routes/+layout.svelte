<script lang="ts">
	import { page } from '$app/state';
	import favicon from '#lib/assets/favicon.svg';
	import { appVersion } from '#lib/sidecar';
	import '#lib/theme.css';

	let { children } = $props();
	let version = $state('0.1.0');

	const links = [
		{ href: '/', label: 'Dashboard' },
		{ href: '/wallet', label: 'Wallet' },
		{ href: '/files', label: 'Files' },
		{ href: '/smart', label: 'Smart' },
		{ href: '/knowledge', label: 'Knowledge' },
		{ href: '/transactions', label: 'Transactions' },
		{ href: '/blockchain', label: 'Blockchain' },
		{ href: '/network', label: 'Network' },
		{ href: '/settings', label: 'Settings' }
	];

	$effect(() => {
		appVersion().then((v) => {
			version = v;
			if (typeof document !== 'undefined') {
				document.title = `Beez Desktop v${v}`;
			}
		});
	});
</script>

<svelte:head>
	<link rel="icon" href={favicon} />
	<title>Beez Desktop v{version}</title>
</svelte:head>

<div class="shell">
	<aside class="sidebar">
		<div class="brand">
			BEEZ
			<small>Desktop v{version}</small>
		</div>
		<nav>
			{#each links as link}
				<a href={link.href} class:active={page.url.pathname === link.href}>{link.label}</a>
			{/each}
		</nav>
	</aside>
	<main>
		{@render children()}
	</main>
</div>
