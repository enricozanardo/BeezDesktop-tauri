<script lang="ts" module>
	export type WorkspaceFile = {
		file_id: string;
		file_name?: string;
		num_chunks?: number;
		indexed_at?: string | null;
	};
</script>

<script lang="ts">
	let {
		files = [],
		selected = $bindable<string[]>([]),
		selectable = true,
		busy = false,
		onremove
	}: {
		files?: WorkspaceFile[];
		selected?: string[];
		selectable?: boolean;
		busy?: boolean;
		onremove?: (file: WorkspaceFile) => void;
	} = $props();

	let query = $state('');

	const visible = $derived(
		files.filter((f) => {
			const q = query.trim().toLowerCase();
			if (!q) return true;
			return (f.file_name || '').toLowerCase().includes(q) || f.file_id.toLowerCase().startsWith(q);
		})
	);

	function toggle(id: string) {
		selected = selected.includes(id) ? selected.filter((s) => s !== id) : [...selected, id];
	}

	function selectVisible() {
		selected = [...new Set([...selected, ...visible.map((f) => f.file_id)])];
	}

	function displayName(f: WorkspaceFile): string {
		return f.file_name || `Unnamed document ${f.file_id.slice(0, 8)}`;
	}
</script>

<div class="ws-picker">
	<div class="row">
		<input
			type="search"
			class="grow"
			bind:value={query}
			placeholder="Search your indexed documents by name…"
		/>
		<span class="meta">{visible.length} of {files.length}</span>
		{#if selectable}
			<button class="ghost" onclick={selectVisible} disabled={!visible.length}>Select shown</button>
			<button class="ghost" onclick={() => (selected = [])} disabled={!selected.length}>Clear</button>
		{/if}
	</div>
	{#if visible.length}
		<ul class="ws-list">
			{#each visible as f (f.file_id)}
				<li class:selected={selected.includes(f.file_id)}>
					<label>
						{#if selectable}
							<input
								type="checkbox"
								checked={selected.includes(f.file_id)}
								onchange={() => toggle(f.file_id)}
							/>
						{/if}
						<span class="stack" style="gap:0.1rem;min-width:0">
							<span class="name" title={f.file_name || f.file_id}>{displayName(f)}</span>
							<span class="meta" style="margin:0">
								{f.num_chunks ?? 0} passages
								{#if f.indexed_at} · indexed {String(f.indexed_at).slice(0, 10)}{/if}
								· id {f.file_id.slice(0, 8)}
							</span>
						</span>
					</label>
					{#if onremove}
						<button class="ghost" disabled={busy} onclick={() => onremove?.(f)}>Remove</button>
					{/if}
				</li>
			{/each}
		</ul>
	{:else if files.length}
		<p class="meta">No indexed document matches “{query}”.</p>
	{/if}
</div>
