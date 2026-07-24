/**
 * 通用防抖 Hook
 *
 * 在 value 变化后等待 delay 毫秒再更新返回值；
 * 若在等待期内 value 再次变化，则重置计时器。
 *
 * @example
 *   const debounced = useDebounce(searchTerm, 300);
 *   useEffect(() => { doSearch(debounced); }, [debounced]);
 */

import { useEffect, useState } from 'react';

export function useDebounce<T>(value: T, delay: number): T {
    const [debounced, setDebounced] = useState<T>(value);

    useEffect(() => {
        const timer = setTimeout(() => setDebounced(value), delay);
        return () => clearTimeout(timer);
    }, [value, delay]);

    return debounced;
}

export default useDebounce;
