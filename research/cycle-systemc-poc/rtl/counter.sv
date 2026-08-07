module counter(input logic clk, reset_n, enable,
               output logic [7:0] count);
  always_ff @(posedge clk or negedge reset_n) begin
    if (!reset_n) count <= '0;
    else if (enable) count <= count + 8'd1;
  end
endmodule

