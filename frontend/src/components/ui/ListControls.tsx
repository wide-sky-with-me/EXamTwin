import { Button, Flex, Input, Space, Typography } from "antd";
import { ChevronLeft, ChevronRight, RotateCcw, Search } from "lucide-react";
import { useEffect, useRef } from "react";
import type { FormEvent, ReactNode } from "react";

const ALL_VALUE = "__all__";

type ListFilterBarProps = {
  ariaLabel: string;
  query: string;
  queryLabel: string;
  queryPlaceholder: string;
  onQueryChange: (query: string) => void;
  onSearch: () => void;
  onReset: () => void;
  resetDisabled?: boolean;
  children?: ReactNode;
  actions?: ReactNode;
};

export function ListFilterBar({
  ariaLabel,
  query,
  queryLabel,
  queryPlaceholder,
  onQueryChange,
  onSearch,
  onReset,
  resetDisabled = false,
  children,
  actions,
}: ListFilterBarProps) {
  const onSearchRef = useRef(onSearch);
  const searchTimerRef = useRef<number | null>(null);
  const readyRef = useRef(false);

  useEffect(() => {
    onSearchRef.current = onSearch;
  }, [onSearch]);

  useEffect(() => {
    if (!readyRef.current) {
      readyRef.current = true;
      return;
    }
    searchTimerRef.current = window.setTimeout(() => onSearchRef.current(), 220);
    return () => {
      if (searchTimerRef.current !== null) window.clearTimeout(searchTimerRef.current);
    };
  }, [query]);

  function submitSearch(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (searchTimerRef.current !== null) window.clearTimeout(searchTimerRef.current);
    onSearchRef.current();
  }

  return (
    <form aria-label={ariaLabel} onSubmit={submitSearch}>
      <Flex align="center" gap="small" wrap="wrap">
        <Input
          allowClear
          aria-label={queryLabel}
          autoComplete="off"
          enterKeyHint="search"
          name="query"
          onChange={(event) => onQueryChange(event.target.value)}
          placeholder={`${queryPlaceholder}…`}
          prefix={<Search aria-hidden="true" size={16} />}
          spellCheck={false}
          style={{ flex: "1 1 260px", maxWidth: 480 }}
          type="search"
          value={query}
        />
        {children}
        <Space>
          <Button htmlType="submit" type="primary">搜索</Button>
          <Button
            aria-label="重置"
            disabled={resetDisabled}
            icon={<RotateCcw aria-hidden="true" size={15} />}
            onClick={onReset}
            title="重置筛选"
            type="default"
          />
          {actions}
        </Space>
      </Flex>
    </form>
  );
}

type FilterOption = {
  label: string;
  value: string;
};

type ListFilterSelectProps = {
  ariaLabel: string;
  onValueChange: (value: string) => void;
  options: readonly FilterOption[];
  value: string;
};

export function ListFilterSelect({
  ariaLabel,
  onValueChange,
  options,
  value,
}: ListFilterSelectProps) {
  return (
    <select
      aria-label={ariaLabel}
      className="list-filter-select-trigger"
      onChange={(event) => onValueChange(event.target.value === ALL_VALUE ? "" : event.target.value)}
      value={value || ALL_VALUE}
    >
      {options.map((option) => (
        <option key={option.value || ALL_VALUE} value={option.value || ALL_VALUE}>
          {option.label}
        </option>
      ))}
    </select>
  );
}

type ListPaginationProps = {
  ariaLabel: string;
  itemUnit: string;
  itemName: string;
  pageSizeLabel?: string;
  total: number;
  page: number;
  pageSize: number;
  visibleCount: number;
  disabled?: boolean;
  pageSizes?: readonly number[];
  onPageChange: (page: number) => void;
  onPageSizeChange: (pageSize: number) => void;
};

const DEFAULT_PAGE_SIZES = [10, 20, 50] as const;

export function ListPagination({
  ariaLabel,
  itemUnit,
  itemName,
  pageSizeLabel,
  total,
  page,
  pageSize,
  visibleCount,
  disabled = false,
  pageSizes = DEFAULT_PAGE_SIZES,
  onPageChange,
  onPageSizeChange,
}: ListPaginationProps) {
  if (total === 0) return null;

  const totalPages = Math.max(1, Math.ceil(total / pageSize));
  const currentPage = Math.min(page, totalPages - 1);
  const firstItem = currentPage * pageSize + 1;
  const lastItem = currentPage * pageSize + visibleCount;
  const resolvedPageSizeLabel = pageSizeLabel ?? `每页显示${itemName}数`;

  return (
    <Flex align="center" aria-label={ariaLabel} justify="space-between" role="navigation" wrap="wrap" gap="small">
      <Typography.Text>
        <strong>{firstItem}–{lastItem}</strong>/<span> {total} {itemUnit}</span>
      </Typography.Text>
      <Space>
        <select
          aria-label={resolvedPageSizeLabel}
          disabled={disabled}
          onChange={(event) => onPageSizeChange(Number(event.target.value))}
          value={String(pageSize)}
        >
          {pageSizes.map((size) => (
            <option key={size} value={String(size)}>{size} {itemUnit}/页</option>
          ))}
        </select>
        <Typography.Text aria-live="polite">{currentPage + 1} / {totalPages}</Typography.Text>
        <Button
          aria-label={`上一页${itemName}`}
          disabled={currentPage === 0 || disabled}
          icon={<ChevronLeft size={17} />}
          onClick={() => onPageChange(currentPage - 1)}
          shape="circle"
        />
        <Button
          aria-label={`下一页${itemName}`}
          disabled={currentPage >= totalPages - 1 || disabled}
          icon={<ChevronRight size={17} />}
          onClick={() => onPageChange(currentPage + 1)}
          shape="circle"
        />
      </Space>
    </Flex>
  );
}
