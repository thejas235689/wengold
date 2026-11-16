module dma_formal (
  input logic clk, rst_n, start, cpu, ready
);
  wire gd, gc, valid, irq;
  wire [3:0] addr;
  wire [7:0] data;
  wire accept_dma = gd && ready;
  preview_arbiter arb(clk, rst_n, valid, cpu, ready, gd, gc);
  preview_dma dut(clk, rst_n, start, accept_dma, valid, irq, addr, data);

  // External transaction model. Count accepted DMA writes, never internal state.
  logic past_valid = 0;
  logic active = 0, first_accepted = 0, completion_due = 0;
  always @(posedge clk) begin
    past_valid <= 1;
    if (!past_valid) assume (!rst_n);
    if (past_valid && rst_n && $past(rst_n && gc && !ready)) assume (cpu);

    if (past_valid) begin
      valid_matches_transfer: assert (valid == active);
      irq_matches_second_acceptance: assert (irq == completion_due);
      if (active)
        offered_beat_matches_transaction: assert (
          {addr, data} == (first_accepted ? {4'd5, 8'hA7} : {4'd4, 8'h39})
        );
      if (!$past(rst_n)) begin
        reset_clears_dma: assert (!valid && !irq);
      end

      if (rst_n) begin
        completed_transfer: cover (irq);
        stalled_dma_then_accepted: cover ($past(rst_n && gd && !ready) && accept_dma);
      end
      reset_after_first_beat: cover (!rst_n && active && first_accepted);
    end

    completion_due <= 0;
    if (!rst_n) begin
      active <= 0;
      first_accepted <= 0;
    end else if (!active && start) begin
      active <= 1;
      first_accepted <= 0;
    end else if (active && accept_dma) begin
      if (!first_accepted) first_accepted <= 1;
      else begin
        active <= 0;
        completion_due <= 1;
      end
    end
  end
endmodule
