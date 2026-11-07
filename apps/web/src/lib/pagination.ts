export function paginationPages(page: number, totalPages: number): (number | "ellipsis")[] {
  if (totalPages <= 7)
    return Array.from({ length: totalPages }, (_, index) => index + 1);

  let start = Math.max(2, Math.min(page - 1, totalPages - 3));
  let end = Math.min(totalPages - 1, Math.max(page + 1, 4));
  if (start === 3) start = 2;
  if (end === totalPages - 2) end = totalPages - 1;

  const pages: (number | "ellipsis")[] = [1];
  if (start > 2) pages.push("ellipsis");
  for (let value = start; value <= end; value++) pages.push(value);
  if (end < totalPages - 1) pages.push("ellipsis");
  pages.push(totalPages);
  return pages;
}
