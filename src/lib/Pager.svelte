<script lang="ts">
	let {
		total,
		offset = $bindable(0),
		limit,
		onchange = () => {}
	}: { total: number; offset: number; limit: number; onchange?: () => void } = $props();

	const page = $derived(Math.floor(offset / limit) + 1);
	const pages = $derived(Math.max(1, Math.ceil(total / limit)));

	function go(p: number) {
		offset = (Math.min(Math.max(p, 1), pages) - 1) * limit;
		onchange();
	}
</script>

{#if total > limit}
	<div class="pager">
		<button class="ghost" disabled={page <= 1} onclick={() => go(1)} aria-label="First page">«</button>
		<button class="ghost" disabled={page <= 1} onclick={() => go(page - 1)}>Previous</button>
		<span>Page {page} of {pages} · {total} items</span>
		<button class="ghost" disabled={page >= pages} onclick={() => go(page + 1)}>Next</button>
		<button class="ghost" disabled={page >= pages} onclick={() => go(pages)} aria-label="Last page">»</button>
	</div>
{/if}
