pass 2: no change
- param-gated paths (FRAME_FIFO=0: full_wr, send_frame_reg, wr_ptr_update toggle; MARK_WHEN_FULL=0: mark_frame_reg; PAUSE_ENABLE=0: pause ports) already minor or interface-only; drop_frame_reg kept major since default config sets it on source reset mid-frame (L404-411); s/m_rst_sync3_reg are RESET-flagged, not anchored; MEDIUM view = 15 anchors (large core, <= 20).
