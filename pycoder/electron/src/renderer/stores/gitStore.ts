/**
 * Git Store — Git 状态、Diff、提交设置
 */
import { create } from 'zustand';
import type { DiffFile, GitStatus } from '../types';

interface GitState {
    gitStatus: GitStatus | null;
    setGitStatus: (status: GitStatus | null) => void;

    pendingDiffs: DiffFile[];
    setPendingDiffs: (diffs: DiffFile[]) => void;

    autoCommitEnabled: boolean;
    commitMsgMode: 'auto' | 'confirm' | 'manual';
    setAutoCommitEnabled: (enabled: boolean) => void;
    setCommitMsgMode: (mode: 'auto' | 'confirm' | 'manual') => void;
}

export const useGitStore = create<GitState>((set) => ({
    gitStatus: null,
    setGitStatus: (status) => set({ gitStatus: status }),

    pendingDiffs: [],
    setPendingDiffs: (diffs) => set({ pendingDiffs: diffs }),

    autoCommitEnabled: false,
    commitMsgMode: 'confirm',
    setAutoCommitEnabled: (enabled) => set({ autoCommitEnabled: enabled }),
    setCommitMsgMode: (mode) => set({ commitMsgMode: mode }),
}));
