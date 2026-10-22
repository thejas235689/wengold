// The same counter with the wrap missing — `count <= MAX` has a counterexample.
module counter_bad (
    input  logic       clk,
    input  logic       rst_n,
    input  logic       en
);
    parameter int MAX = 4;
    logic [2:0] count;

    always_ff @(posedge clk) begin
        if (!rst_n)      count <= 0;
        else if (en)     count <= count + 1;
    end
endmodule
