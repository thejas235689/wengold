module subsystem_tb;
  logic clk = 0, rst_n = 0, start = 0, cpu = 0, stall = 0;
  logic ready, irq, dma, gd, gc;
  logic [3:0] rd = 0;
  wire [3:0] addr;
  wire [7:0] data, value;
  preview_subsystem dut(.clk(clk), .rst_n(rst_n), .start(start), .cpu(cpu),
                        .stall(stall), .read_addr(rd), .ready(ready), .irq(irq),
                        .dma(dma), .gd(gd), .gc(gc), .write_addr(addr),
                        .write_data(data), .read_data(value), .dma_addr(), .dma_data());
  always #5 clk = ~clk;

  int cycle = 0, beats = 0, cpu_beats = 0, irqs = 0;
  logic held = 0;
  logic saw_fresh_contention = 0;
  logic [13:0] expected_offer;
  always @(posedge clk) begin
    if (rst_n) begin
      cycle = cycle + 1;
      if (held) begin
        if ({gd, gc, addr, data} !== expected_offer)
          $fatal(1, "FAIL:REQ-HOLD:%0d", cycle);
        $display("HIT:REQ-HOLD");
      end
      if (!held && dma && cpu && ready && !saw_fresh_contention) begin
`ifdef EXPECT_DMA_FIRST
        if (!gd || gc) $fatal(1, "FAIL:REQ-PRIORITY:%0d", cycle);
`else
        if (!gc || gd) $fatal(1, "FAIL:REQ-PRIORITY:%0d", cycle);
`endif
        saw_fresh_contention = 1;
        $display("HIT:REQ-PRIORITY");
      end
      held = !ready && (gd || gc);
      expected_offer = {gd, gc, addr, data};
      if (gd && gc) $fatal(1, "FAIL:REQ-ARBITRATE:%0d", cycle);
      if (dma && cpu && ready) $display("HIT:REQ-ARBITRATE");
      if (gd && ready) beats = beats + 1;
      if (gc && ready) cpu_beats = cpu_beats + 1;
      #1;
      if (irq) begin
        if (beats != 2 || irqs != 0) $fatal(1, "FAIL:REQ-IRQ:%0d", cycle);
        irqs = irqs + 1;
        $display("HIT:REQ-IRQ");
      end
    end
  end

  task automatic check_memory(input logic [3:0] a, input logic [7:0] want);
    rd = a;
    #1;
    if (value !== want) $fatal(1, "FAIL:REQ-DATA:%0d", cycle);
  endtask

  initial begin
    @(negedge clk);
    if ({dma, irq, gd, gc} !== 4'b0) $fatal(1, "FAIL:REQ-RESET:0");
    $display("HIT:REQ-RESET");
    rst_n = 1;
    start = 1;
    @(negedge clk);
    start = 0;
`ifndef NO_STALL
    stall = 1;
    @(negedge clk);
`endif
    cpu = 1;
`ifndef NO_STALL
    repeat (2) @(negedge clk);
    stall = 0;
`endif
    while (cpu_beats == 0) @(negedge clk);
    cpu = 0;
    repeat (4) @(negedge clk);
    if (beats != 2 || cpu_beats != 1) $fatal(1, "FAIL:REQ-DATA:%0d", cycle);
    check_memory(4, 8'h39);
    check_memory(5, 8'hA7);
    check_memory(2, 8'hE2);
    check_memory(6, 8'h00);
    $display("HIT:REQ-DATA");
    if (irqs != 1 || irq !== 1'b0) $fatal(1, "FAIL:REQ-IRQ:%0d", cycle);
    $display("SOC_PREVIEW_PASS");
    $finish;
  end
  initial begin
    #500;
    $fatal(1, "scenario timeout");
  end
endmodule
