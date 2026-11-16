module subsystem_formal (
  input logic clk, rst_n, start, cpu, stall
);
  (* anyconst *) logic [3:0] watched_addr;
  wire ready, irq, dma, gd, gc;
  wire [3:0] write_addr, dma_addr;
  wire [7:0] write_data, read_data, dma_data;
  preview_subsystem dut(clk, rst_n, start, cpu, stall, watched_addr, ready,
                        irq, dma, gd, gc, write_addr, write_data, read_data, dma_addr, dma_data);

  logic past_valid = 0;
  logic active = 0, second = 0, completion_due = 0;
  logic [7:0] expected_word = 0;
  // The scoreboard derives address/data from the request owner and its own
  // beat count. It does not consume write_addr/data when computing readback.
  wire [3:0] expected_addr = gd ? (second ? 4'd5 : 4'd4) : 4'd2;
  wire [7:0] expected_data = gd ? (second ? 8'hA7 : 8'h39) : 8'hE2;
  wire accept = rst_n && !stall && (gd || gc);

  always @(posedge clk) begin
    past_valid <= 1;
    if (!past_valid) assume (!rst_n);
    if (past_valid && rst_n && $past(rst_n && gc && stall)) assume (cpu);

    if (past_valid) begin
      ready_matches_stall: assert (ready == !stall);
      active_matches_dma_request: assert (dma == active);
      irq_matches_accepted_transfer: assert (irq == completion_due);
      watched_subsystem_readback: assert (read_data == expected_word);
      // Auxiliary invariant: CPU arbitration can hide the DMA beat from the
      // bus for arbitrarily long. Track it even while the CPU owns the port.
      if (active) begin
        dma_offer_matches_model: assert (
          {dma_addr, dma_data} == (second ? {4'd5, 8'hA7} : {4'd4, 8'h39})
        );
      end
      if (rst_n && (gd || gc)) begin
        selected_owner_is_legal: assert (!(gd && gc) && (gd ? active : cpu));
        write_address_matches_owner: assert (write_addr == expected_addr);
        write_payload_matches_owner: assert (write_data == expected_data);
      end
      if (rst_n && $past(rst_n && stall && (gd || gc))) begin
        stalled_write_is_stable: assert (
          {gd,gc,write_addr,write_data} == $past({gd,gc,write_addr,write_data})
        );
      end
      cover_first_dma_readback: cover (rst_n && watched_addr == 4'd4 && read_data == 8'h39);
      cover_second_dma_readback: cover (rst_n && irq && watched_addr == 4'd5 && read_data == 8'hA7);
      cover_cpu_readback: cover (rst_n && watched_addr == 4'd2 && read_data == 8'hE2);
      cover_stall_then_accept: cover (accept && gd && $past(rst_n && gd && stall && cpu));
    end

    completion_due <= 0;
    if (!rst_n) begin
      expected_word <= 0;
      active <= 0;
      second <= 0;
    end else begin
      if (accept && expected_addr == watched_addr) expected_word <= expected_data;
      if (!active && start) begin
        active <= 1;
        second <= 0;
      end else if (accept && gd) begin
        if (second) begin
          active <= 0;
          completion_due <= 1;
        end else second <= 1;
      end
    end
  end
endmodule
