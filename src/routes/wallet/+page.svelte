<script lang="ts">
	import { sidecarCall } from '#lib';

	let status = $state<Record<string, unknown> | null>(null);
	let mnemonic = $state('');
	let createdMnemonic = $state('');
	let message = $state('');
	let busy = $state(false);
	let loaded = $state(false);

	async function refresh() {
		status = await sidecarCall('wallet_status');
	}

	$effect(() => {
		if (loaded) return;
		loaded = true;
		refresh();
	});

	async function create() {
		busy = true;
		message = '';
		createdMnemonic = '';
		const r = await sidecarCall('wallet_create');
		busy = false;
		if (r.ok === false) {
			message = String(r.error);
			return;
		}
		createdMnemonic = String(r.mnemonic || '');
		message = `Wallet created: ${r.address}. Write down the mnemonic — it is shown once.`;
		await refresh();
	}

	async function importWallet() {
		busy = true;
		message = '';
		const r = await sidecarCall('wallet_import', { mnemonic });
		busy = false;
		if (r.ok === false) {
			message = String(r.error);
			return;
		}
		mnemonic = '';
		message = `Imported: ${r.address}`;
		await refresh();
	}

	async function forget() {
		if (!confirm('Delete the Beez Desktop Two wallet from this machine?')) return;
		busy = true;
		const r = await sidecarCall('wallet_forget');
		busy = false;
		message = r.ok ? 'Wallet removed from this app.' : String(r.error);
		createdMnemonic = '';
		await refresh();
	}
</script>

<h1>Wallet</h1>
<p class="lead">
	Generate or import a BIP39 mnemonic. Stored encrypted under BeezDesktopTwo (independent of Toga).
	If you previously used Toga Beez Desktop on this machine, Two migrates that wallet once on first load.
</p>

<div class="card">
	<strong>Status</strong>
	{#if status?.has_wallet}
		<p class="mono">{String(status.address)}</p>
		<p class="meta">Storage: {String(status.storage || 'BeezDesktopTwo')}</p>
		<button class="ghost" onclick={forget} disabled={busy}>Forget wallet</button>
	{:else}
		<p class="meta">No wallet on disk.</p>
	{/if}
	{#if status?.ok === false}
		<p class="meta" style="color: var(--danger)">{String(status.error)}</p>
		{#if status.hint}<pre>{String(status.hint)}</pre>{/if}
	{/if}
</div>

{#if !status?.has_wallet}
	<div class="card">
		<strong>Create new wallet</strong>
		<p class="meta">Generates a new 12-word mnemonic and saves it for this app only.</p>
		<button class="primary" onclick={create} disabled={busy}>Generate wallet</button>
		{#if createdMnemonic}
			<pre class="mnemonic">{createdMnemonic}</pre>
		{/if}
	</div>

	<div class="card">
		<strong>Import mnemonic</strong>
		<textarea bind:value={mnemonic} placeholder="twelve or twenty four words…" rows="3"></textarea>
		<button class="primary" onclick={importWallet} disabled={busy || !mnemonic.trim()}>Import</button>
	</div>
{/if}

{#if message}
	<p class="meta">{message}</p>
{/if}

<style>
	.mono {
		font-family: ui-monospace, monospace;
		word-break: break-all;
	}
	.mnemonic {
		margin-top: 0.75rem;
		white-space: pre-wrap;
	}
	textarea {
		width: 100%;
		margin: 0.75rem 0;
	}
</style>
