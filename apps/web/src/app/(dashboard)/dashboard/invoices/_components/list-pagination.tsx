"use client";

import { ChevronLeft, ChevronRight } from "lucide-react";

import { Button } from "@/components/ui/button";

export interface ListPaginationProps {
  page: number; // 1-based
  pageCount: number;
  onPageChange: (page: number) => void;
  /** 1-based inclusive range currently shown, for the "Showing X–Y" line. */
  rangeStart: number;
  rangeEnd: number;
  totalRows: number;
}

/**
 * Client-side pagination for the filtered list. Prev/Next plus an explicit
 * range line — the total shown is "of N loaded" (the API returns bare arrays
 * without a total; the page's Load-more control extends the loaded window).
 */
export function ListPagination({
  page,
  pageCount,
  onPageChange,
  rangeStart,
  rangeEnd,
  totalRows,
}: ListPaginationProps) {
  if (totalRows === 0) return null;

  return (
    <div className="flex flex-wrap items-center justify-between gap-3">
      <p className="text-sm text-muted-foreground" role="status">
        Showing {rangeStart}–{rangeEnd} of {totalRows} loaded
      </p>
      {pageCount > 1 && (
        <div className="flex items-center gap-2">
          <Button
            variant="outline"
            size="sm"
            onClick={() => onPageChange(page - 1)}
            disabled={page <= 1}
          >
            <ChevronLeft />
            Previous
          </Button>
          <span className="text-sm text-muted-foreground">
            Page {page} of {pageCount}
          </span>
          <Button
            variant="outline"
            size="sm"
            onClick={() => onPageChange(page + 1)}
            disabled={page >= pageCount}
          >
            Next
            <ChevronRight />
          </Button>
        </div>
      )}
    </div>
  );
}
