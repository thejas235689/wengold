module arbiter_formal (
  input logic clk, rst_n, dma, cpu, ready
);
  wire gd, gc;
  preview_arbiter dut(clk, rst_n, dma, cpu, ready, gd, gc);

  logic past_valid = 0;
  logic [2:0] denied = 0;
`ifdef EXPECT_DMA_FIRST
  wire low_req = cpu, low_grant = gc;
`else
  wire low_req = dma, low_grant = gd;
`endif

  always @(posedge clk) begin
    past_valid <= 1;
    if (!past_valid) assume (!rst_n);

    if (rst_n) begin
      // REQ-ARBITRATE: exclusivity and no spurious or missing grant.
      mutual_exclusion: assert (!(gd && gc));
      grant_has_request: assert ((!gd || dma) && (!gc || cpu));

      // Requesters must keep a selected offer alive until acceptance or reset.
      if (past_valid && $past(rst_n && !ready && (gd || gc))) begin
        if ($past(gd)) assume (dma);
        if ($past(gc)) assume (cpu);
        stall_holds_owner: assert ({gd, gc} == $past({gd, gc}));
        stall_then_accept: cover (ready && dma && cpu);
      end else begin
        fresh_grants_pending_request: assert ((gd || gc) == (dma || cpu));
        if (dma && cpu) begin
`ifdef EXPECT_DMA_FIRST
          fresh_priority: assert (gd && !gc);
`else
          fresh_priority: assert (gc && !gd);
`endif
          fresh_contended_accept: cover (ready);
        end
      end
    end
    if (!rst_n || !ready || !low_req || low_grant)
      denied <= 0;
    else if (denied < 4)
      denied <= denied + 1'b1;

    // A cover, not a fairness proof. Ready is high throughout the streak.
`ifdef CHECK_BOUNDED_SERVICE
    four_ready_cycle_service: assert (!rst_n || denied < 4);
`endif
    low_priority_denied_four_ready_cycles: cover (rst_n && denied == 4);
  end
endmodule
